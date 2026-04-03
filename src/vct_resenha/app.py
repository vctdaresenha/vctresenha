import json
import ctypes
from ctypes import wintypes
import os
import queue
import random
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from PIL import Image, ImageTk

from .bracket import (
    build_resolved_matches,
    clean_lines,
    infer_bracket_size,
    match_can_receive_result,
    match_display_label,
    winner_slot_from_name,
)
from .config import load_app_settings
from .desktop_portal_client import PortalAdminClient, PortalClientError
from .models import SUPPORTED_BRACKET_SIZES, get_bracket_template
from .storage import StateStorage
from .valorant_api import (
    DEFAULT_COMPETITIVE_ROTATION,
    HenrikRateLimitError,
    fetch_latest_match,
    get_henrik_api_keys,
    parse_riot_id,
    split_henrik_api_keys,
    validate_br_riot_id,
)


class ChampionshipApp(tk.Tk):
    GA_ROOT = 2
    GWL_STYLE = -16
    GWL_EXSTYLE = -20
    WM_NCLBUTTONDOWN = 0x00A1
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_SYSMENU = 0x00080000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    WS_POPUP = 0x80000000
    WS_EX_APPWINDOW = 0x00040000
    WS_EX_TOOLWINDOW = 0x00000080
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_FRAMECHANGED = 0x0020
    HTCAPTION = 2
    HTLEFT = 10
    HTRIGHT = 11
    HTTOP = 12
    HTTOPLEFT = 13
    HTTOPRIGHT = 14
    HTBOTTOM = 15
    HTBOTTOMLEFT = 16
    HTBOTTOMRIGHT = 17
    MONITOR_DEFAULTTONEAREST = 2

    def __init__(self) -> None:
        super().__init__()
        self.title("VCT da Resenha")
        self.minsize(1280, 720)
        self._set_initial_window_geometry()
        self.withdraw()
        self.wm_attributes("-alpha", 0.0)

        self.source_path = Path(__file__).resolve().parents[2]
        self.base_path = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else self.source_path
        self.settings = load_app_settings(self.base_path)
        self.portal_client = PortalAdminClient(self.settings)
        self.storage = StateStorage(self.base_path)
        self.state = self.storage.load()
        self._normalize_team_profiles()
        self._normalize_team_draw()
        self._normalize_map_draft()
        self.all_map_catalog = self._load_local_map_catalog()
        self._normalize_map_pool()
        self.resolved_matches: list[dict] = []
        self.match_options: dict[str, str] = {}
        self.current_tab_index = 0
        self.is_maximized = False
        self.restore_geometry = self.geometry()
        self.native_hwnd: int | None = None
        self.bracket_card_items: dict[str, list[int]] = {}
        self.bracket_logo_refs: list[tk.PhotoImage] = []
        self.public_team_logo_refs: list[tk.PhotoImage] = []
        self.public_match_logo_refs: list[tk.PhotoImage] = []
        self.admin_logo_preview: tk.PhotoImage | None = None
        self.admin_authenticated = False
        self.panel_window: tk.Toplevel | None = None
        self.panel_window_host: tk.Frame | None = None
        self.public_match_resize_job: str | None = None
        self.validation_in_progress = False
        self.public_teams_mode = "menu"
        self.team_draw_animation_active = False
        self.team_draw_animation_jobs: list[str] = []
        self.admin_team_form_state: list[dict] = []
        self.portal_pending_submissions: list[dict] = []
        self.portal_users: list[dict] = []
        self.portal_registrations_open = True
        self.selected_portal_user_id: int | None = None
        self.app_feedback_var = tk.StringVar(value="")
        self.app_feedback_clear_job: str | None = None
        self.mousewheel_routes: dict[str, tk.Widget] = {}
        self.map_catalog = self._build_fallback_map_catalog()
        self.map_catalog_loaded = True
        self.map_board_contexts: dict[str, dict] = {}
        self.map_image_cache: dict[str, object] = {}
        self.public_map_timeline_signature: tuple[tuple[str, str, str, str], ...] = ()
        self.public_map_revealed_decider: str = ""
        self.public_map_pending_decider: str = ""
        self.home_button_specs = [
            ("PAINEL", 0),
            ("CARTAS", 1),
            ("TIMES", 2),
            ("CHAVE", 3),
            ("MAPAS", 4),
            ("PARTIDAS", 5),
        ]
        self.content_nav_specs = [
            ("PAINEL", 0),
            ("CARTAS", 1),
            ("TIMES", 2),
            ("CHAVE", 3),
            ("MAPAS", 4),
            ("PARTIDAS", 5),
        ]
        self.home_button_items: dict[str, dict] = {}
        self.content_nav_items: dict[int, dict] = {}
        self.logo_source: tk.PhotoImage | None = None
        self.logo_image: tk.PhotoImage | None = None
        self._bind_global_mousewheel_events()
        self.icon_image: tk.PhotoImage | None = None
        self.logo_item: int | None = None
        self.last_logo_scale = 1
        self.home_is_visible = True
        self.title_font_family = "Segoe UI"
        self.button_font_family = "Bahnschrift Condensed"
        self.app_fullscreen = False

        self._load_custom_fonts()
        self._configure_style()
        self._build_layout()
        self._populate_widgets_from_state()
        self._refresh_everything(preserve_selected_match=True)
        self.bind("<Map>", self._handle_window_map)
        self.bind("<F11>", self._toggle_app_fullscreen)
        self.bind("<Escape>", self._exit_app_fullscreen)
        self.after(20, self._show_initial_window)

    def _set_initial_window_geometry(self) -> None:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        window_width = min(1600, max(1280, screen_width - 180))
        window_height = min(900, max(720, screen_height - 180))
        offset_x = max((screen_width - window_width) // 2, 0)
        offset_y = max((screen_height - window_height) // 2, 0)
        self.geometry(f"{window_width}x{window_height}+{offset_x}+{offset_y}")

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Root.TFrame", background="#0b0b0c")
        style.configure("Card.TFrame", background="#111214")
        style.configure("Title.TLabel", font=(self.title_font_family, 22, "bold"), background="#111214", foreground="#f3f3f3")
        style.configure(
            "Subtitle.TLabel",
            font=(self.title_font_family, 10),
            background="#111214",
            foreground="#8a8f98",
        )
        style.configure("Section.TLabel", font=(self.title_font_family, 12, "bold"), background="#111214", foreground="#f3f3f3")
        style.configure("Primary.TButton", padding=(14, 8), font=(self.title_font_family, 10, "bold"))
        style.configure("Treeview", rowheight=28)
        style.configure("Content.TNotebook", background="#0b0b0c", borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.layout("Content.TNotebook.Tab", [])
        self.configure(bg="#060606")

    def _build_layout(self) -> None:
        self.root_frame = tk.Frame(self, bg="#0b0b0c")
        self.root_frame.pack(fill="both", expand=True)

        self._build_title_bar()
        self._build_resize_handles()

        self.body_frame = tk.Frame(self.root_frame, bg="#0b0b0c")
        self.body_frame.pack(fill="both", expand=True)

        self.home_view = tk.Frame(self.body_frame, bg="#0b0b0c")
        self.content_view = ttk.Frame(self.body_frame, style="Root.TFrame")

        self.home_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.content_view.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_home_view()
        self._build_content_view()
        self._show_home_screen()

    def _build_title_bar(self) -> None:
        self.title_bar = tk.Frame(self.root_frame, bg="#070707", height=44)
        self.title_bar.pack(fill="x", side="top")
        self.title_bar.pack_propagate(False)

        self.title_bar.bind("<ButtonPress-1>", self._begin_native_drag)
        self.title_bar.bind("<Double-Button-1>", lambda _event: self._toggle_maximize())

        title_label = tk.Label(
            self.title_bar,
            text="VCT DA RESENHA",
            bg="#070707",
            fg="#f4f4f4",
            font=(self.button_font_family, 18),
            padx=16,
            pady=6,
        )
        title_label.pack(side="left")
        title_label.bind("<ButtonPress-1>", self._begin_native_drag)
        title_label.bind("<Double-Button-1>", lambda _event: self._toggle_maximize())

        drag_fill = tk.Frame(self.title_bar, bg="#070707")
        drag_fill.pack(side="left", fill="both", expand=True)
        drag_fill.bind("<ButtonPress-1>", self._begin_native_drag)
        drag_fill.bind("<Double-Button-1>", lambda _event: self._toggle_maximize())

        self.app_feedback_label = tk.Label(
            self.title_bar,
            textvariable=self.app_feedback_var,
            bg="#070707",
            fg="#9ca3ad",
            anchor="e",
            font=(self.title_font_family, 10, "bold"),
            padx=12,
        )
        self.app_feedback_label.pack(side="right")

        controls = tk.Frame(self.title_bar, bg="#070707")
        controls.pack(side="right")

        self.minimize_button = self._create_titlebar_button(controls, "_", self._minimize_window)
        self.maximize_button = self._create_titlebar_button(controls, "[ ]", self._toggle_maximize)
        self.close_button = self._create_titlebar_button(controls, "X", self.destroy, hover_bg="#b00020")

    def _clear_app_feedback(self) -> None:
        self.app_feedback_clear_job = None
        if hasattr(self, "app_feedback_var"):
            self.app_feedback_var.set("")

    def _set_app_feedback(self, message: str, tone: str = "info", persist_ms: int = 4200) -> None:
        palette = {
            "info": "#aeb7c2",
            "success": "#7ed7a7",
            "warning": "#f0c36c",
            "error": "#ef8f8f",
        }
        feedback_text = str(message or "").strip()
        if not feedback_text:
            self._clear_app_feedback()
            return
        self.app_feedback_var.set(feedback_text)
        if hasattr(self, "app_feedback_label"):
            self.app_feedback_label.configure(fg=palette.get(tone, palette["info"]))
        if self.app_feedback_clear_job is not None:
            self.after_cancel(self.app_feedback_clear_job)
            self.app_feedback_clear_job = None
        if persist_ms > 0:
            self.app_feedback_clear_job = self.after(persist_ms, self._clear_app_feedback)

    def _build_resize_handles(self) -> None:
        handle_specs = {
            "n": {"cursor": "sb_v_double_arrow", "hit": self.HTTOP, "place": {"x": 8, "y": 0, "relwidth": 1.0, "width": -16, "height": 5}},
            "s": {"cursor": "sb_v_double_arrow", "hit": self.HTBOTTOM, "place": {"x": 8, "rely": 1.0, "y": -5, "relwidth": 1.0, "width": -16, "height": 5}},
            "w": {"cursor": "sb_h_double_arrow", "hit": self.HTLEFT, "place": {"x": 0, "y": 8, "width": 5, "relheight": 1.0, "height": -16}},
            "e": {"cursor": "sb_h_double_arrow", "hit": self.HTRIGHT, "place": {"relx": 1.0, "x": -5, "y": 8, "width": 5, "relheight": 1.0, "height": -16}},
            "nw": {"cursor": "size_nw_se", "hit": self.HTTOPLEFT, "place": {"x": 0, "y": 0, "width": 8, "height": 8}},
            "ne": {"cursor": "size_ne_sw", "hit": self.HTTOPRIGHT, "place": {"relx": 1.0, "x": -8, "y": 0, "width": 8, "height": 8}},
            "sw": {"cursor": "size_ne_sw", "hit": self.HTBOTTOMLEFT, "place": {"x": 0, "rely": 1.0, "y": -8, "width": 8, "height": 8}},
            "se": {"cursor": "size_nw_se", "hit": self.HTBOTTOMRIGHT, "place": {"relx": 1.0, "rely": 1.0, "x": -8, "y": -8, "width": 8, "height": 8}},
        }
        self.resize_handles = {}
        for edge, config in handle_specs.items():
            handle = tk.Frame(self.root_frame, bg="#070707", cursor=config["cursor"])
            handle.place(**config["place"])
            handle.bind("<ButtonPress-1>", lambda _event, hit=config["hit"]: self._begin_native_resize(hit))
            self.resize_handles[edge] = handle

    def _create_titlebar_button(self, parent: tk.Widget, text: str, command, hover_bg: str = "#181818") -> tk.Label:
        button = tk.Label(
            parent,
            text=text,
            bg="#070707",
            fg="#f4f4f4",
            width=5,
            height=2,
            font=(self.title_font_family, 10, "bold"),
            cursor="hand2",
        )
        button.default_bg = "#070707"
        button.pack(side="left")
        button.bind("<Button-1>", lambda _event: command())
        button.bind("<Enter>", lambda _event: button.configure(bg=hover_bg))
        button.bind("<Leave>", lambda _event: button.configure(bg=button.default_bg))
        return button

    def _build_home_view(self) -> None:
        self.home_canvas = tk.Canvas(self.home_view, highlightthickness=0, bd=0, bg="#0b0b0c")
        self.home_canvas.pack(fill="both", expand=True)
        self.home_canvas.bind("<Configure>", self._redraw_home_screen)

        self._load_logo_asset()
        for label, tab_index in self.home_button_specs:
            text_id = self.home_canvas.create_text(
                0,
                0,
                text=label,
                fill="#f3f3f3",
                anchor="w",
                font=(self.button_font_family, 48),
                tags=(f"menu:{label}", "home-menu"),
            )
            underline_id = self.home_canvas.create_line(
                0,
                0,
                0,
                0,
                fill="#ffffff",
                width=4,
                state="hidden",
                tags=(f"menu:{label}", "home-menu"),
            )
            self.home_button_items[label] = {
                "text_id": text_id,
                "underline_id": underline_id,
                "tab_index": tab_index,
            }
            self.home_canvas.tag_bind(f"menu:{label}", "<Enter>", lambda _event, value=label: self._set_home_hover(value, True))
            self.home_canvas.tag_bind(f"menu:{label}", "<Leave>", lambda _event, value=label: self._set_home_hover(value, False))
            self.home_canvas.tag_bind(f"menu:{label}", "<Button-1>", lambda _event, index=tab_index: self._open_section(index))

    def _build_content_view(self) -> None:
        self.content_view.columnconfigure(0, weight=1)
        self.content_view.rowconfigure(1, weight=1)

        header = tk.Frame(self.content_view, bg="#111214", padx=24, pady=20)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        self.back_button = tk.Button(
            header,
            text="< INICIO",
            command=self._go_back,
            relief="flat",
            borderwidth=0,
            bg="#111111",
            fg="#f2f2f2",
            activebackground="#1d1d1d",
            activeforeground="#ffffff",
            cursor="hand2",
            font=(self.button_font_family, 18),
            padx=18,
            pady=8,
        )
        self.back_button.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 18))

        nav_frame = tk.Frame(header, bg="#111214")
        nav_frame.grid(row=0, column=1, sticky="e")
        self._build_content_nav(nav_frame)

        notebook_wrap = ttk.Frame(self.content_view, style="Root.TFrame", padding=(18, 8, 18, 18))
        notebook_wrap.grid(row=1, column=0, sticky="nsew")
        notebook_wrap.columnconfigure(0, weight=1)
        notebook_wrap.rowconfigure(0, weight=1)

        self.notebook = ttk.Notebook(notebook_wrap, style="Content.TNotebook")
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook.bind("<<NotebookTabChanged>>", self._handle_tab_change)

        self.panel_tab = ttk.Frame(self.notebook, style="Root.TFrame", padding=16)
        self.cards_tab = ttk.Frame(self.notebook, style="Root.TFrame", padding=16)
        self.teams_tab = ttk.Frame(self.notebook, style="Root.TFrame", padding=16)
        self.bracket_tab = ttk.Frame(self.notebook, style="Root.TFrame", padding=16)
        self.matches_tab = ttk.Frame(self.notebook, style="Root.TFrame", padding=16)
        self.maps_tab = ttk.Frame(self.notebook, style="Root.TFrame", padding=16)

        self.notebook.add(self.panel_tab, text="Painel")
        self.notebook.add(self.cards_tab, text="Cartas")
        self.notebook.add(self.teams_tab, text="Times")
        self.notebook.add(self.bracket_tab, text="Chave")
        self.notebook.add(self.maps_tab, text="Mapas")
        self.notebook.add(self.matches_tab, text="Partidas")

        self.tab_frames = [self.panel_tab, self.cards_tab, self.teams_tab, self.bracket_tab, self.maps_tab, self.matches_tab]

        self._build_panel_tab()
        self._build_cards_tab()
        self._build_teams_tab()
        self._build_bracket_tab()
        self._build_matches_tab()
        self._build_maps_tab()
        self._update_back_button_state()

    def _build_content_nav(self, parent: tk.Widget) -> None:
        for label, tab_index in self.content_nav_specs:
            item_frame = tk.Frame(parent, bg="#111214")
            item_frame.pack(side="left", padx=14)

            button = tk.Label(
                item_frame,
                text=label,
                bg="#111214",
                fg="#8a8f98",
                cursor="hand2",
                font=(self.button_font_family, 18),
            )
            button.pack(side="top")
            underline = tk.Frame(item_frame, bg="#111214", height=3, width=64)
            underline.pack(side="top", pady=(5, 0), fill="x")

            button.bind("<Enter>", lambda _event, index=tab_index: self._set_content_nav_hover(index, True))
            button.bind("<Leave>", lambda _event, index=tab_index: self._set_content_nav_hover(index, False))
            button.bind("<Button-1>", lambda _event, index=tab_index: self._select_tab(index))

            self.content_nav_items[tab_index] = {
                "button": button,
                "underline": underline,
            }

    def _build_panel_tab(self, host: tk.Widget | None = None) -> None:
        panel_host = host or self.panel_tab
        for child in panel_host.winfo_children():
            child.destroy()
        panel_host.columnconfigure(0, weight=1)
        panel_host.rowconfigure(0, weight=1)

        self.panel_root = tk.Frame(panel_host, bg="#0b0b0c")
        self.panel_root.grid(row=0, column=0, sticky="nsew")
        self.panel_root.columnconfigure(0, weight=1)
        self.panel_root.rowconfigure(0, weight=1)

        self.panel_login_view = tk.Frame(self.panel_root, bg="#0b0b0c")
        self.panel_login_view.grid(row=0, column=0, sticky="nsew")
        self.panel_login_view.columnconfigure(0, weight=1)
        self.panel_login_view.rowconfigure(0, weight=1)

        login_card = tk.Frame(self.panel_login_view, bg="#111214", highlightthickness=1, highlightbackground="#232427")
        login_card.grid(row=0, column=0)
        login_card.columnconfigure(0, weight=1)

        tk.Label(
            login_card,
            text="PAINEL ADMINISTRATIVO",
            bg="#111214",
            fg="#f3f3f3",
            font=(self.button_font_family, 30),
            padx=34,
            pady=26,
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            login_card,
            text="Entre com o usuario administrador para editar times, chave e partidas.",
            bg="#111214",
            fg="#8a8f98",
            font=(self.title_font_family, 11),
            padx=34,
            pady=0,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 18))

        form = tk.Frame(login_card, bg="#111214", padx=34, pady=8)
        form.grid(row=2, column=0, sticky="ew")
        form.columnconfigure(0, weight=1)

        self.admin_username_var = tk.StringVar(value=self.settings.admin.username)
        self.admin_password_var = tk.StringVar()
        self.admin_login_feedback_var = tk.StringVar(value="")

        tk.Label(form, text="Usuario", bg="#111214", fg="#d8dade", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=0, column=0, sticky="ew")
        self.admin_username_entry = tk.Entry(form, textvariable=self.admin_username_var, relief="flat", bg="#1a1b1d", fg="#f3f3f3", insertbackground="#f3f3f3", font=(self.title_font_family, 11))
        self.admin_username_entry.grid(row=1, column=0, sticky="ew", pady=(6, 14), ipady=8)
        tk.Label(form, text="Senha", bg="#111214", fg="#d8dade", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=2, column=0, sticky="ew")
        self.admin_password_entry = tk.Entry(form, textvariable=self.admin_password_var, show="*", relief="flat", bg="#1a1b1d", fg="#f3f3f3", insertbackground="#f3f3f3", font=(self.title_font_family, 11))
        self.admin_password_entry.grid(row=3, column=0, sticky="ew", pady=(6, 10), ipady=8)
        self.admin_password_entry.bind("<Return>", lambda _event: self._attempt_admin_login())
        tk.Label(form, textvariable=self.admin_login_feedback_var, bg="#111214", fg="#d86b6b", anchor="w", font=(self.title_font_family, 10)).grid(row=4, column=0, sticky="ew")
        tk.Button(
            form,
            text="ENTRAR NO PAINEL",
            command=self._attempt_admin_login,
            relief="flat",
            borderwidth=0,
            bg="#f3f3f3",
            fg="#0b0b0c",
            activebackground="#ffffff",
            activeforeground="#000000",
            cursor="hand2",
            font=(self.button_font_family, 18),
            padx=12,
            pady=10,
        ).grid(row=5, column=0, sticky="ew", pady=(18, 30))

        self.panel_admin_view = tk.Frame(self.panel_root, bg="#f4f6f8")
        self.panel_admin_view.grid(row=0, column=0, sticky="nsew")
        self.panel_admin_view.columnconfigure(0, weight=1)
        self.panel_admin_view.rowconfigure(1, weight=1)

        admin_header = tk.Frame(self.panel_admin_view, bg="#f4f6f8", padx=8, pady=8)
        admin_header.grid(row=0, column=0, sticky="ew")
        admin_header.columnconfigure(1, weight=1)

        tk.Label(admin_header, text="PAINEL", bg="#f4f6f8", fg="#111111", font=(self.button_font_family, 24)).grid(row=0, column=0, sticky="w")
        tk.Label(admin_header, text="Area interna para administrar os dados do aplicativo.", bg="#f4f6f8", fg="#5f6771", font=(self.title_font_family, 10)).grid(row=1, column=0, sticky="w")
        tk.Button(
            admin_header,
            text="ABRIR PORTAL",
            command=self._open_portal_site,
            relief="flat",
            borderwidth=0,
            bg="#111111",
            fg="#f2f2f2",
            activebackground="#1d1d1d",
            activeforeground="#ffffff",
            cursor="hand2",
            font=(self.button_font_family, 14),
            padx=14,
            pady=6,
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 10))
        tk.Button(
            admin_header,
            text="ABRIR PASTA DE DADOS",
            command=self._open_data_folder,
            relief="flat",
            borderwidth=0,
            bg="#f3f3f3",
            fg="#111111",
            activebackground="#ffffff",
            activeforeground="#000000",
            cursor="hand2",
            font=(self.button_font_family, 14),
            padx=14,
            pady=6,
        ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 10))
        tk.Button(
            admin_header,
            text="SAIR",
            command=self._logout_admin,
            relief="flat",
            borderwidth=0,
            bg="#111111",
            fg="#f2f2f2",
            activebackground="#1d1d1d",
            activeforeground="#ffffff",
            cursor="hand2",
            font=(self.button_font_family, 16),
            padx=16,
            pady=6,
        ).grid(row=0, column=3, rowspan=2, sticky="e")

        self.admin_notebook = ttk.Notebook(self.panel_admin_view)
        self.admin_notebook.grid(row=1, column=0, sticky="nsew")
        self.admin_notebook.bind("<<NotebookTabChanged>>", self._handle_admin_panel_tab_change)

        self.admin_teams_tab = ttk.Frame(self.admin_notebook, style="Root.TFrame", padding=16)
        self.admin_portal_tab = ttk.Frame(self.admin_notebook, style="Root.TFrame", padding=16)
        self.admin_users_tab = ttk.Frame(self.admin_notebook, style="Root.TFrame", padding=16)
        self.admin_bracket_tab = ttk.Frame(self.admin_notebook, style="Root.TFrame", padding=16)
        self.admin_matches_tab = ttk.Frame(self.admin_notebook, style="Root.TFrame", padding=16)
        self.admin_maps_tab = ttk.Frame(self.admin_notebook, style="Root.TFrame", padding=16)

        self.admin_notebook.add(self.admin_teams_tab, text="Times")
        self.admin_notebook.add(self.admin_portal_tab, text="Portal")
        self.admin_notebook.add(self.admin_users_tab, text="Usuarios")
        self.admin_notebook.add(self.admin_bracket_tab, text="Chave")
        self.admin_notebook.add(self.admin_matches_tab, text="Partidas")
        self.admin_notebook.add(self.admin_maps_tab, text="Mapas")

        self._build_admin_teams_tab()
        self._build_admin_portal_tab()
        self._build_admin_users_tab()
        self._build_admin_bracket_tab()
        self._build_admin_matches_tab()
        self._build_admin_maps_tab()
        self._update_panel_login_state()

    def _open_panel_window(self) -> None:
        if self.panel_window and self.panel_window.winfo_exists():
            self.panel_window.deiconify()
            self.panel_window.lift()
            self.panel_window.focus_force()
            return

        self.panel_window = tk.Toplevel(self)
        self.panel_window.title("Painel - VCT da Resenha")
        self.panel_window.geometry("1380x860")
        self.panel_window.minsize(1180, 760)
        self.panel_window.configure(bg="#0b0b0c")
        if self.icon_image:
            try:
                self.panel_window.iconphoto(True, self.icon_image)
            except tk.TclError:
                pass

        self.panel_window.columnconfigure(0, weight=1)
        self.panel_window.rowconfigure(0, weight=1)
        self.panel_window_host = tk.Frame(self.panel_window, bg="#0b0b0c")
        self.panel_window_host.grid(row=0, column=0, sticky="nsew")
        self._build_panel_tab(self.panel_window_host)
        self.panel_window.protocol("WM_DELETE_WINDOW", self._close_panel_window)

    def _close_panel_window(self) -> None:
        if self.panel_window and self.panel_window.winfo_exists():
            self.panel_window.destroy()
        self.panel_window = None
        self.panel_window_host = None
        self._build_panel_tab()
        self._populate_widgets_from_state()
        self._refresh_everything(preserve_selected_match=True)

    def _open_data_folder(self) -> None:
        data_folder = self.storage.file_path.parent
        data_folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(data_folder))
        except OSError:
            messagebox.showerror("Dados", f"Nao foi possivel abrir a pasta de dados:\n{data_folder}")

    def _load_logo_asset(self) -> None:
        logo_path = self._resolve_resource_path("assets", "vctdaresenha.png")
        if logo_path.exists():
            self.logo_source = tk.PhotoImage(file=str(logo_path))
        icon_path = self._resolve_resource_path("assets", "iconresenha.png")
        if icon_path.exists():
            try:
                self.icon_image = tk.PhotoImage(file=str(icon_path))
                self.iconphoto(True, self.icon_image)
            except tk.TclError:
                pass

    def _resolve_resource_path(self, *parts: str) -> Path:
        if getattr(sys, "frozen", False):
            external_path = self.base_path.joinpath(*parts)
            if external_path.exists():
                return external_path
            return Path(sys._MEIPASS).joinpath(*parts)
        return self.source_path.joinpath(*parts)

    def _load_custom_fonts(self) -> None:
        font_path = self._resolve_resource_path("assets", "bebas.ttf")
        if not font_path.exists():
            return

        try:
            ctypes.windll.gdi32.AddFontResourceExW(str(font_path), 0x10, 0)
        except Exception:
            return

        available_families = {family.lower(): family for family in tkfont.families(self)}
        for family_name in ("bebas neue", "bebas", "bebas neue regular"):
            if family_name in available_families:
                self.button_font_family = available_families[family_name]
                break

    def _blank_team_profile(self, slot_index: int) -> dict:
        return {
            "slot": slot_index,
            "name": "",
            "logo_path": "",
            "portal_view_url": "",
            "coach": "",
            "players": ["", "", "", "", ""],
        }

    def _normalize_team_profiles(self) -> None:
        raw_profiles = self.state.get("team_profiles", [])
        if not raw_profiles:
            raw_profiles = []
            for index, team in enumerate(self.state.get("generated_teams", [])[:8]):
                raw_profiles.append(
                    {
                        "slot": index,
                        "name": team.get("name", ""),
                        "logo_path": "",
                        "coach": "",
                        "players": (team.get("players", []) + ["", "", "", "", ""])[:5],
                    }
                )
            if not raw_profiles:
                for index, team_name in enumerate(self.state.get("registered_teams", [])[:8]):
                    raw_profiles.append(
                        {
                            "slot": index,
                            "name": team_name,
                            "logo_path": "",
                            "coach": "",
                            "players": ["", "", "", "", ""],
                        }
                    )

        normalized_profiles: list[dict] = []
        for slot_index in range(8):
            source = raw_profiles[slot_index] if slot_index < len(raw_profiles) else {}
            players = source.get("players", []) if isinstance(source, dict) else []
            normalized_profiles.append(
                {
                    "slot": slot_index,
                    "name": source.get("name", "") if isinstance(source, dict) else "",
                    "logo_path": source.get("logo_path", "") if isinstance(source, dict) else "",
                    "portal_view_url": source.get("portal_view_url", "") if isinstance(source, dict) else "",
                    "coach": source.get("coach", "") if isinstance(source, dict) else "",
                    "players": (list(players) + ["", "", "", "", ""])[:5],
                }
            )
        self.state["team_profiles"] = normalized_profiles

    def _get_team_profiles(self) -> list[dict]:
        self._normalize_team_profiles()
        return self.state["team_profiles"]

    def _normalize_team_draw(self) -> None:
        draw_state = self.state.get("team_draw", {})
        if not isinstance(draw_state, dict):
            draw_state = {}

        active_slots = {
            profile["slot"]
            for profile in self._get_active_team_profiles()
            if profile.get("name", "").strip()
        }

        draw_order: list[int] = []
        for slot_value in draw_state.get("draw_order", []):
            try:
                slot_index = int(slot_value)
            except (TypeError, ValueError):
                continue
            if slot_index in active_slots and slot_index not in draw_order:
                draw_order.append(slot_index)

        current_pair: list[int] = []
        for slot_value in draw_state.get("current_pair", []):
            try:
                slot_index = int(slot_value)
            except (TypeError, ValueError):
                continue
            if slot_index in active_slots and slot_index not in current_pair:
                current_pair.append(slot_index)

        expected_count = len(active_slots)
        is_finalized = bool(draw_state.get("is_finalized")) and expected_count > 0 and len(draw_order) == expected_count
        self.state["team_draw"] = {
            "draw_order": draw_order,
            "current_pair": current_pair[:2],
            "is_finalized": is_finalized,
        }

    def _get_team_draw_state(self) -> dict:
        self._normalize_team_draw()
        return self.state["team_draw"]

    def _reset_team_draw_state(self, save_state: bool = True, keep_current_pair: bool = False) -> None:
        current_pair = self._get_team_draw_state().get("current_pair", []) if keep_current_pair else []
        self.state["team_draw"] = {
            "draw_order": [],
            "current_pair": current_pair[:2],
            "is_finalized": False,
        }
        if save_state:
            self._save_state()

    def _sync_team_draw_state(self) -> None:
        active_slots = [profile["slot"] for profile in self._get_active_team_profiles() if profile.get("name", "").strip()]
        draw_state = self._get_team_draw_state()
        valid_order = [slot for slot in draw_state.get("draw_order", []) if slot in active_slots]
        if valid_order != draw_state.get("draw_order", []) or len(active_slots) != len(valid_order) and draw_state.get("is_finalized"):
            draw_state["draw_order"] = valid_order
            draw_state["is_finalized"] = bool(draw_state.get("is_finalized")) and len(valid_order) == len(active_slots)
        valid_pair = [slot for slot in draw_state.get("current_pair", []) if slot in active_slots]
        if valid_pair != draw_state.get("current_pair", []):
            draw_state["current_pair"] = valid_pair[:2]

    def _get_active_draw_profiles(self) -> list[dict]:
        return [profile for profile in self._get_active_team_profiles() if profile.get("name", "").strip()]

    def _get_draw_slot_to_profile(self) -> dict[int, dict]:
        return {profile["slot"]: profile for profile in self._get_active_draw_profiles()}

    def _normalize_map_draft(self) -> None:
        draft = self.state.get("map_draft", {})
        if not isinstance(draft, dict):
            draft = {}
        actions = draft.get("actions", [])
        if not isinstance(actions, list):
            actions = []
        self.state["map_draft"] = {
            "team_one_slot": int(draft.get("team_one_slot", 0) or 0),
            "team_two_slot": int(draft.get("team_two_slot", 1) or 1),
            "series_type": draft.get("series_type", "MD3") if draft.get("series_type", "MD3") in {"MD1", "MD3", "MD5"} else "MD3",
            "actions": actions,
        }

    def _get_map_draft(self) -> dict:
        self._normalize_map_draft()
        return self.state["map_draft"]

    def _load_local_map_catalog(self) -> list[dict]:
        manifest_path = self._resolve_resource_path("assets", "mapas", "catalog.json")
        if manifest_path.exists():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                payload = []
            catalog: list[dict] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if not name:
                    continue
                file_name = str(item.get("file", "")).strip()
                image_path = self._resolve_resource_path("assets", "mapas", file_name) if file_name else Path()
                catalog.append(
                    {
                        "name": name,
                        "image_path": str(image_path) if file_name and image_path.exists() else "",
                        "image_url": "",
                        "splash_url": "",
                        "icon_url": "",
                        "uuid": "",
                    }
                )
            if catalog:
                return catalog
        return [
            {
                "name": name,
                "image_path": str(self._resolve_map_asset_path(name)) if self._resolve_map_asset_path(name).exists() else "",
                "image_url": "",
                "splash_url": "",
                "icon_url": "",
                "uuid": "",
            }
            for name in DEFAULT_COMPETITIVE_ROTATION
        ]

    def _normalize_map_pool(self) -> None:
        available_names = [item["name"] for item in self.all_map_catalog]
        configured_pool = self.state.get("map_pool", [])
        if not isinstance(configured_pool, list):
            configured_pool = []
        normalized_pool: list[str] = []
        for name in configured_pool:
            normalized_name = str(name).strip()
            if normalized_name and normalized_name in available_names and normalized_name not in normalized_pool:
                normalized_pool.append(normalized_name)
        if not normalized_pool:
            normalized_pool = available_names[:7] if len(available_names) >= 7 else available_names[:]
        self.state["map_pool"] = normalized_pool

    def _get_map_pool(self) -> list[str]:
        self._normalize_map_pool()
        return list(self.state.get("map_pool", []))

    def _build_fallback_map_catalog(self) -> list[dict]:
        selected_pool = self._get_map_pool()
        catalog_by_name = {item["name"]: item for item in self.all_map_catalog}
        return [catalog_by_name[name] for name in selected_pool if name in catalog_by_name]

    def _slugify_map_name(self, map_name: str) -> str:
        sanitized = "".join(character.lower() if character.isalnum() else "-" for character in map_name.strip())
        while "--" in sanitized:
            sanitized = sanitized.replace("--", "-")
        return sanitized.strip("-") or "mapa"

    def _resolve_map_asset_path(self, map_name: str) -> Path:
        return self._resolve_resource_path("assets", "mapas", f"{self._slugify_map_name(map_name)}.png")

    def _get_map_sequence(self, series_type: str) -> list[dict]:
        if series_type == "MD1":
            return [
                {"type": "ban", "team": 0},
                {"type": "ban", "team": 1},
                {"type": "ban", "team": 0},
                {"type": "ban", "team": 1},
                {"type": "ban", "team": 0},
                {"type": "ban", "team": 1},
            ]
        if series_type == "MD5":
            return [
                {"type": "ban", "team": 0},
                {"type": "ban", "team": 1},
                {"type": "pick", "team": 0},
                {"type": "pick", "team": 1},
                {"type": "pick", "team": 0},
                {"type": "pick", "team": 1},
            ]
        return [
            {"type": "ban", "team": 0},
            {"type": "ban", "team": 1},
            {"type": "pick", "team": 0},
            {"type": "pick", "team": 1},
            {"type": "ban", "team": 0},
            {"type": "ban", "team": 1},
        ]

    def _get_team_profile_by_slot(self, slot_index: int) -> dict:
        profiles = self._get_team_profiles()
        if 0 <= slot_index < len(profiles):
            return profiles[slot_index]
        return self._blank_team_profile(slot_index)

    def _get_map_team_choices(self) -> list[tuple[str, int]]:
        choices: list[tuple[str, int]] = []
        for profile in self._get_active_team_profiles():
            name = profile.get("name", "").strip() or f"Time {profile['slot'] + 1}"
            choices.append((name, profile["slot"]))
        return choices

    def _get_active_team_profiles(self) -> list[dict]:
        team_count = int(self.state.get("team_count", 4))
        return self._get_team_profiles()[:team_count]

    def _load_map_image(self, map_name: str, max_size: tuple[int, int] = (208, 150)) -> tk.PhotoImage | None:
        image_path = self._resolve_map_asset_path(map_name)
        if not image_path.exists():
            return None

        cache_key = f"{image_path}|{max_size[0]}x{max_size[1]}"
        if cache_key in self.map_image_cache:
            return self.map_image_cache[cache_key]

        try:
            image = tk.PhotoImage(file=str(image_path))
        except tk.TclError:
            return None

        width_scale = max(1, (image.width() + max_size[0] - 1) // max_size[0])
        height_scale = max(1, (image.height() + max_size[1] - 1) // max_size[1])
        scale = max(width_scale, height_scale)
        if scale > 1:
            image = image.subsample(scale, scale)
        self.map_image_cache[cache_key] = image
        return image

    def _load_map_cover_image(self, map_name: str, size: tuple[int, int], grayscale: bool = False) -> ImageTk.PhotoImage | None:
        image_path = self._resolve_map_asset_path(map_name)
        if not image_path.exists():
            return None

        cache_key = f"cover|{image_path}|{size[0]}x{size[1]}|gray={int(grayscale)}"
        if cache_key in self.map_image_cache:
            return self.map_image_cache[cache_key]  # type: ignore[return-value]

        try:
            image = Image.open(image_path).convert("RGBA")
        except OSError:
            return None

        target_width, target_height = size
        source_ratio = image.width / max(image.height, 1)
        target_ratio = target_width / max(target_height, 1)

        if source_ratio > target_ratio:
            crop_height = image.height
            crop_width = int(crop_height * target_ratio)
        else:
            crop_width = image.width
            crop_height = int(crop_width / max(target_ratio, 0.01))

        left = max((image.width - crop_width) // 2, 0)
        top = max((image.height - crop_height) // 2, 0)
        image = image.crop((left, top, left + crop_width, top + crop_height))
        image = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        if grayscale:
            image = image.convert("L").convert("RGBA")
        photo_image = ImageTk.PhotoImage(image)
        self.map_image_cache[cache_key] = photo_image
        return photo_image

    def _get_public_map_display_items(self, statuses: dict[str, dict], include_decider: bool = True) -> list[dict]:
        draft = self._get_map_draft()
        items: list[dict] = []
        for action in draft.get("actions", []):
            map_name = action.get("map_name", "")
            if map_name not in statuses:
                continue
            payload = dict(statuses[map_name])
            payload["map_name"] = map_name
            items.append(payload)

        decider_name = next((name for name, payload in statuses.items() if payload.get("state") == "decider"), "")
        if decider_name and include_decider:
            payload = dict(statuses[decider_name])
            payload["map_name"] = decider_name
            items.append(payload)
        return items

    def _load_logo_image(self, logo_path: str, max_size: int = 72) -> tk.PhotoImage | None:
        if not logo_path:
            return None
        try:
            image = tk.PhotoImage(file=logo_path)
        except tk.TclError:
            return None

        max_dimension = max(image.width(), image.height(), 1)
        scale = max(1, (max_dimension + max_size - 1) // max_size)
        if scale > 1:
            image = image.subsample(scale, scale)
        return image

    def _attempt_admin_login(self) -> None:
        username = self.admin_username_var.get().strip()
        password = self.admin_password_var.get().strip()
        if username == self.settings.admin.username and password == self.settings.admin.password:
            self.admin_authenticated = True
            self.admin_password_var.set("")
            self.admin_login_feedback_var.set("")
            self._update_panel_login_state()
            return

        self.admin_authenticated = False
        self.admin_login_feedback_var.set("Usuario ou senha invalidos.")
        self._update_panel_login_state()

    def _logout_admin(self) -> None:
        self.admin_authenticated = False
        self.admin_password_var.set("")
        self.admin_login_feedback_var.set("")
        self._update_panel_login_state()

    def _update_panel_login_state(self) -> None:
        if self.admin_authenticated:
            self.panel_login_view.tkraise()
            self.panel_admin_view.tkraise()
            self._refresh_admin_team_slots()
            self._refresh_admin_team_editor_from_state()
            self._refresh_portal_admin_dashboard()
            self._populate_admin_bracket_from_profiles()
            self._sync_map_draft_controls_from_state()
            self._refresh_map_pool_editor()
        else:
            self.panel_admin_view.lower()
            self.panel_login_view.tkraise()
            self.admin_username_entry.focus_set()

    def _open_portal_site(self) -> None:
        portal_url = self.settings.portal.base_url.strip()
        if not portal_url:
            self._set_app_feedback("Defina portal.base_url em config/app_settings.json antes de abrir o site.", tone="warning")
            return
        webbrowser.open(portal_url)

    def _open_portal_page(self, url: str, missing_message: str) -> None:
        normalized_url = str(url or "").strip()
        if not normalized_url:
            self._set_app_feedback(missing_message, tone="warning")
            return
        webbrowser.open(normalized_url)

    def _bind_global_mousewheel_events(self) -> None:
        self.bind_all("<MouseWheel>", self._handle_global_mousewheel, add="+")
        self.bind_all("<Button-4>", self._handle_global_mousewheel, add="+")
        self.bind_all("<Button-5>", self._handle_global_mousewheel, add="+")

    def _register_mousewheel_route(self, widget: tk.Widget, target: tk.Widget | None = None) -> None:
        self.mousewheel_routes[str(widget)] = target or widget

    def _resolve_mousewheel_target(self, widget: tk.Widget | None) -> tk.Widget | None:
        current = widget
        while current is not None:
            routed_target = self.mousewheel_routes.get(str(current))
            if routed_target is not None:
                return routed_target
            if hasattr(current, "yview_scroll") and current.winfo_class() in {"Text", "Listbox", "Canvas"}:
                return current
            current = current.master
        return None

    def _handle_global_mousewheel(self, event) -> str | None:
        widget_under_pointer = self.winfo_containing(event.x_root, event.y_root)
        target = self._resolve_mousewheel_target(widget_under_pointer)
        if target is None:
            return None
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            raw_delta = getattr(event, "delta", 0)
            if raw_delta == 0:
                return None
            delta = -int(raw_delta / 120) if raw_delta % 120 == 0 else (-1 if raw_delta > 0 else 1)
        try:
            target.yview_scroll(delta, "units")
        except tk.TclError:
            return None
        return "break"

    def _update_scrollable_canvas_width(self, canvas: tk.Canvas, window_id: int) -> None:
        canvas.itemconfigure(window_id, width=max(canvas.winfo_width(), 1))

    def _create_scrollable_container(self, parent: tk.Widget, bg: str = "#0b0b0c", show_scrollbar: bool = False) -> tuple[tk.Frame, tk.Canvas, tk.Frame]:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)

        shell = tk.Frame(parent, bg=bg)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(shell, bg=bg, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        if show_scrollbar:
            scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            canvas.configure(yscrollcommand=scrollbar.set)

        content = tk.Frame(canvas, bg=bg)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event, target_canvas=canvas: target_canvas.configure(scrollregion=target_canvas.bbox("all")))
        canvas.bind("<Configure>", lambda _event, target_canvas=canvas, target_window=window_id: self._update_scrollable_canvas_width(target_canvas, target_window))

        self._register_mousewheel_route(shell, canvas)
        self._register_mousewheel_route(canvas, canvas)
        self._register_mousewheel_route(content, canvas)
        return shell, canvas, content

    def _ensure_admin_team_form_state(self) -> None:
        if self.admin_team_form_state:
            return
        for slot_index in range(8):
            self.admin_team_form_state.append(
                {
                    "slot": slot_index,
                    "name_var": tk.StringVar(),
                    "coach_var": tk.StringVar(),
                    "logo_var": tk.StringVar(),
                    "player_vars": [tk.StringVar() for _ in range(5)],
                    "logo_label": None,
                }
            )

    def _handle_admin_team_canvas_resize(self, _event=None) -> None:
        if not hasattr(self, "admin_team_canvas"):
            return
        canvas_width = max(self.admin_team_canvas.winfo_width(), 1)
        self.admin_team_canvas.itemconfigure(self.admin_team_canvas_window, width=canvas_width)

    def _build_admin_team_editor_cards(self) -> None:
        if not hasattr(self, "admin_team_cards_frame"):
            return
        self._ensure_admin_team_form_state()
        for child in self.admin_team_cards_frame.winfo_children():
            child.destroy()

        active_count = int(self.state.get("team_count", 4))
        for column_index in range(2):
            self.admin_team_cards_frame.columnconfigure(column_index, weight=1)

        for slot_index in range(active_count):
            form_state = self.admin_team_form_state[slot_index]
            card = tk.Frame(self.admin_team_cards_frame, bg="#17181c", highlightthickness=1, highlightbackground="#26292e", padx=16, pady=16)
            card.grid(row=slot_index // 2, column=slot_index % 2, sticky="nsew", padx=8, pady=8)
            card.columnconfigure(1, weight=1)

            tk.Label(card, text=f"TIME {slot_index + 1}", bg="#17181c", fg="#f3f3f3", font=(self.button_font_family, 20)).grid(row=0, column=0, columnspan=2, sticky="w")

            logo_box = tk.Frame(card, bg="#f4f4f4", width=96, height=96)
            logo_box.grid(row=1, column=0, rowspan=3, sticky="nw", pady=(14, 0), padx=(0, 16))
            logo_box.pack_propagate(False)
            logo_label = tk.Label(logo_box, bg="#f4f4f4", fg="#1b1d20", font=(self.button_font_family, 18))
            logo_label.pack(fill="both", expand=True)
            form_state["logo_label"] = logo_label

            tk.Label(card, text="Nome unico do time", bg="#17181c", fg="#d5dae2", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=1, column=1, sticky="ew", pady=(14, 0))
            tk.Entry(card, textvariable=form_state["name_var"], relief="flat", bg="#101113", fg="#f3f3f3", insertbackground="#f3f3f3").grid(row=2, column=1, sticky="ew", pady=(6, 0))

            tk.Label(card, text="Coach", bg="#17181c", fg="#d5dae2", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=3, column=1, sticky="ew", pady=(12, 0))
            tk.Entry(card, textvariable=form_state["coach_var"], relief="flat", bg="#101113", fg="#f3f3f3", insertbackground="#f3f3f3").grid(row=4, column=1, sticky="ew", pady=(6, 0))

            tk.Button(
                card,
                text="ESCOLHER LOGO 1:1",
                command=lambda current_slot=slot_index: self._choose_team_logo_for_slot(current_slot),
                relief="flat",
                borderwidth=0,
                bg="#26292e",
                fg="#f3f3f3",
                activebackground="#31353b",
                activeforeground="#ffffff",
                cursor="hand2",
                font=(self.button_font_family, 14),
                padx=12,
                pady=8,
            ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(14, 0))

            players_block = tk.Frame(card, bg="#17181c")
            players_block.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 0))
            players_block.columnconfigure(1, weight=1)
            for player_index, player_var in enumerate(form_state["player_vars"], start=1):
                label_text = "★ Capitao" if player_index == 1 else f"Jogador {player_index}"
                tk.Label(players_block, text=label_text, bg="#17181c", fg="#d5dae2", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=player_index - 1, column=0, sticky="w", pady=4)
                tk.Entry(players_block, textvariable=player_var, relief="flat", bg="#101113", fg="#f3f3f3", insertbackground="#f3f3f3").grid(row=player_index - 1, column=1, sticky="ew", pady=4, padx=(12, 0))

            card_actions = tk.Frame(card, bg="#17181c")
            card_actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(14, 0))
            tk.Button(
                card_actions,
                text="VER TIME",
                command=lambda current_slot=slot_index: self._open_team_profile_portal_view(current_slot),
                relief="flat",
                borderwidth=0,
                bg="#f3f3f3",
                fg="#050607",
                activebackground="#ffffff",
                activeforeground="#000000",
                cursor="hand2",
                font=(self.button_font_family, 14),
                padx=12,
                pady=8,
            ).pack(side="left")
            tk.Button(
                card_actions,
                text="LIMPAR SLOT",
                command=lambda current_slot=slot_index: self._clear_admin_team_form_slot(current_slot),
                relief="flat",
                borderwidth=0,
                bg="#1f2023",
                fg="#f3f3f3",
                activebackground="#2b2d31",
                activeforeground="#ffffff",
                cursor="hand2",
                font=(self.button_font_family, 14),
                padx=12,
                pady=8,
            ).pack(side="right")

    def _refresh_admin_team_editor_from_state(self) -> None:
        if not self.admin_team_form_state:
            return
        profiles = self._get_team_profiles()
        for slot_index, form_state in enumerate(self.admin_team_form_state):
            profile = profiles[slot_index]
            form_state["name_var"].set(profile.get("name", ""))
            form_state["coach_var"].set(profile.get("coach", ""))
            form_state["logo_var"].set(profile.get("logo_path", ""))
            for player_index, player_var in enumerate(form_state["player_vars"]):
                player_var.set(profile.get("players", ["", "", "", "", ""])[player_index])
            self._refresh_admin_logo_preview_for_slot(slot_index)

    def _refresh_admin_logo_preview_for_slot(self, slot_index: int) -> None:
        if slot_index >= len(self.admin_team_form_state):
            return
        form_state = self.admin_team_form_state[slot_index]
        logo_label = form_state.get("logo_label")
        if not logo_label:
            return
        logo_image = self._load_logo_image(form_state["logo_var"].get().strip(), max_size=96)
        if logo_image:
            self.public_team_logo_refs.append(logo_image)
            logo_label.configure(image=logo_image, text="")
            logo_label.image = logo_image
        else:
            logo_label.configure(image="", text="LOGO\n96x96")
            logo_label.image = None

    def _choose_team_logo_for_slot(self, slot_index: int) -> None:
        file_path = filedialog.askopenfilename(
            title="Escolher logo do time",
            filetypes=[("Imagens PNG", "*.png"), ("Todas as imagens suportadas", "*.png *.gif *.ppm *.pgm")],
        )
        if not file_path:
            return
        self.admin_team_form_state[slot_index]["logo_var"].set(file_path)
        self._refresh_admin_logo_preview_for_slot(slot_index)

    def _clear_admin_team_form_slot(self, slot_index: int) -> None:
        form_state = self.admin_team_form_state[slot_index]
        form_state["name_var"].set("")
        form_state["coach_var"].set("")
        form_state["logo_var"].set("")
        for player_var in form_state["player_vars"]:
            player_var.set("")
        self._refresh_admin_logo_preview_for_slot(slot_index)

    def _get_team_logo_storage_dir(self) -> Path:
        return self.storage.file_path.parent / "team_logos"

    def _normalize_and_store_team_logo(self, slot_index: int, source_path: str) -> str:
        if not source_path:
            return ""
        output_dir = self._get_team_logo_storage_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"team_{slot_index + 1}.png"
        with Image.open(source_path).convert("RGBA") as image:
            side = min(image.width, image.height)
            left = max((image.width - side) // 2, 0)
            top = max((image.height - side) // 2, 0)
            image = image.crop((left, top, left + side, top + side))
            image = image.resize((256, 256), Image.Resampling.LANCZOS)
            image.save(output_path, format="PNG")
        return str(output_path)

    def _save_all_team_profiles(self) -> None:
        active_count = int(self.team_count_var.get())
        entered_profiles: list[dict] = []
        normalized_names: set[str] = set()
        player_validation_cache: dict[str, dict | None] = {}
        api_keys: list[str] = []

        for slot_index in range(active_count):
            form_state = self.admin_team_form_state[slot_index]
            team_name = form_state["name_var"].get().strip()
            coach_name = form_state["coach_var"].get().strip()
            logo_path = form_state["logo_var"].get().strip()
            players = [player_var.get().strip() for player_var in form_state["player_vars"]]

            if not team_name:
                messagebox.showwarning("Painel", f"O Time {slot_index + 1} precisa ter nome.")
                return
            normalized_name = team_name.lower()
            if normalized_name in normalized_names:
                messagebox.showwarning("Painel", f"O nome '{team_name}' ja esta sendo usado por outro time.")
                return
            normalized_names.add(normalized_name)

            if not logo_path:
                messagebox.showwarning("Painel", f"O Time {slot_index + 1} precisa ter uma logo obrigatoria.")
                return
            if not Path(logo_path).exists():
                messagebox.showwarning("Painel", f"A logo do Time {slot_index + 1} nao foi encontrada no caminho informado.")
                return

            if any(not player for player in players):
                messagebox.showwarning("Painel", f"Preencha os 5 jogadores do Time {slot_index + 1} no formato Nick#TAG.")
                return

            for player_name in players:
                if not parse_riot_id(player_name):
                    messagebox.showwarning("Painel", f"O jogador '{player_name}' precisa estar no formato Nick#TAG.")
                    return

            if players and not api_keys:
                api_keys = self._ensure_henrik_api_keys()
                if not api_keys:
                    messagebox.showwarning("Painel", "Ao menos uma chave valida da API HenrikDev e necessaria para validar os jogadores BR.")
                    return

            try:
                for player_name in players:
                    normalized_player = self._normalize_player_identity(player_name)
                    if normalized_player not in player_validation_cache:
                        cached_validation = self._get_cached_player_validation(player_name)
                        if cached_validation:
                            player_validation_cache[normalized_player] = cached_validation
                        else:
                            player_validation_cache[normalized_player] = validate_br_riot_id(player_name, api_key=api_keys, timeout=6.0)
                            if player_validation_cache[normalized_player]:
                                self._store_cached_player_validation(player_name, player_validation_cache[normalized_player])
                    if not player_validation_cache[normalized_player]:
                        messagebox.showwarning("Painel", f"Nao foi possivel confirmar automaticamente o jogador '{player_name}' na API HenrikDev. Revise o Riot ID e a chave da API.")
                        return
            except PermissionError:
                self._store_henrik_api_keys([])
                self._save_state()
                messagebox.showerror("Painel", "As chaves da API HenrikDev foram rejeitadas durante a validacao dos jogadores.")
                return
            except HenrikRateLimitError as exc:
                messagebox.showerror(
                    "Painel",
                    "A API HenrikDev atingiu o limite de requisicoes para todas as chaves configuradas.\n\n"
                    "Cadastre uma ou mais chaves extras separadas por virgula para distribuir as consultas.\n\n"
                    f"Detalhe: {exc}",
                )
                return
            except Exception as exc:
                messagebox.showerror("Painel", f"Nao foi possivel validar os jogadores do Time {slot_index + 1}.\n\n{exc}")
                return

            try:
                normalized_logo_path = self._normalize_and_store_team_logo(slot_index, logo_path)
            except OSError as exc:
                messagebox.showerror("Painel", f"Nao foi possivel normalizar a logo do Time {slot_index + 1}.\n\n{exc}")
                return

            entered_profiles.append(
                {
                    "slot": slot_index,
                    "name": team_name,
                    "logo_path": normalized_logo_path,
                    "portal_view_url": self._get_team_profiles()[slot_index].get("portal_view_url", ""),
                    "coach": coach_name,
                    "players": players,
                }
            )

        profiles = self._get_team_profiles()
        for slot_index in range(8):
            profiles[slot_index] = entered_profiles[slot_index] if slot_index < len(entered_profiles) else self._blank_team_profile(slot_index)

        self.state["team_profiles"] = profiles
        self._reset_team_draw_state(save_state=False)
        self._save_state()
        self.map_image_cache = {}
        self.admin_team_editor_feedback_var.set("Times salvos com sucesso. O sorteio publico foi reiniciado para refletir os dados novos.")
        self._refresh_everything(preserve_selected_match=True)
        self._refresh_admin_team_editor_from_state()
        self._populate_admin_bracket_from_profiles()

    def _refresh_admin_team_slots(self) -> None:
        if not hasattr(self, "admin_team_slot_listbox"):
            return
        self.admin_team_slot_listbox.delete(0, "end")
        active_count = int(self.state.get("team_count", 4))
        for profile in self._get_team_profiles():
            status = "ativo" if profile["slot"] < active_count else "reserva"
            name = profile["name"] or "Sem nome"
            self.admin_team_slot_listbox.insert("end", f"Time {profile['slot'] + 1} | {name} | {status}")

        current_selection = self.admin_team_slot_listbox.curselection()
        selected_index = current_selection[0] if current_selection else 0
        if self.admin_team_slot_listbox.size() > 0:
            self.admin_team_slot_listbox.selection_set(selected_index)
            self.admin_team_slot_listbox.event_generate("<<ListboxSelect>>")

    def _refresh_portal_admin_dashboard(self) -> None:
        if not hasattr(self, "portal_pending_listbox"):
            return
        try:
            settings_payload = self.portal_client.get_admin_settings()
            self.portal_pending_submissions = self.portal_client.list_pending_submissions()
            approved_teams = self.portal_client.list_approved_teams()
        except PortalClientError as exc:
            self.portal_pending_submissions = []
            self.portal_admin_status_var.set(f"Falha ao conectar ao portal: {exc}")
            self._render_portal_pending_submissions()
            return

        self.portal_registrations_open = bool(settings_payload.get("registrations_open", True))
        if hasattr(self, "portal_registrations_button"):
            self.portal_registrations_button.configure(text="Fechar inscrições" if self.portal_registrations_open else "Abrir inscrições")

        self.portal_admin_status_var.set(
            f"{len(self.portal_pending_submissions)} submissao(oes) pendente(s) | {len(approved_teams)} time(s) aprovado(s) | Inscrições {'abertas' if self.portal_registrations_open else 'fechadas'}."
        )
        self._render_portal_pending_submissions()

    def _render_portal_pending_submissions(self) -> None:
        if not hasattr(self, "portal_pending_listbox"):
            return
        self.portal_pending_listbox.delete(0, "end")
        for item in self.portal_pending_submissions:
            owner_name = str(item.get("owner_name", "Capitao")).strip() or "Capitao"
            team_name = str(item.get("name", "Sem nome")).strip() or "Sem nome"
            self.portal_pending_listbox.insert("end", f"{team_name} | {owner_name}")
        if self.portal_pending_submissions:
            self.portal_pending_listbox.selection_set(0)
            self._load_selected_portal_submission()
        else:
            self.portal_submission_summary_var.set("Nenhuma submissao pendente no momento.")

    def _load_selected_portal_submission(self, _event=None) -> None:
        if not hasattr(self, "portal_pending_listbox"):
            return
        selection = self.portal_pending_listbox.curselection()
        if not selection:
            self.portal_submission_summary_var.set("Selecione uma submissao para revisar os dados enviados.")
            return
        submission = self.portal_pending_submissions[selection[0]]
        players = submission.get("players", []) if isinstance(submission.get("players", []), list) else []
        players_lines = []
        for index, player in enumerate(players):
            prefix = "Capitao" if index == 0 else f"Jogador {index + 1}"
            players_lines.append(f"{prefix}: {player}")
        self.portal_submission_summary_var.set(
            f"Time: {submission.get('name', '-')}\n"
            f"Conta Discord: {submission.get('owner_name', '-')}\n"
            f"Coach: {submission.get('coach', '-')}\n\n"
            f"Lineup\n{'\n'.join(players_lines)}\n\n"
            f"Enviado em: {submission.get('submitted_at', '-')}"
        )

    def _open_selected_portal_submission_view(self) -> None:
        if not hasattr(self, "portal_pending_listbox"):
            return
        selection = self.portal_pending_listbox.curselection()
        if not selection:
            self._set_app_feedback("Selecione uma submissao antes de abrir a pagina do time.", tone="warning")
            return
        submission = self.portal_pending_submissions[selection[0]]
        self._open_portal_page(
            str(submission.get("public_view_url", "")).strip(),
            "Essa submissao ainda nao possui uma pagina publica disponivel.",
        )

    def _toggle_portal_registrations(self) -> None:
        next_state = not self.portal_registrations_open
        try:
            payload = self.portal_client.set_registrations_open(next_state)
        except PortalClientError as exc:
            self._set_app_feedback(str(exc), tone="error", persist_ms=7000)
            return
        self.portal_registrations_open = bool(payload.get("registrations_open", next_state))
        self._refresh_portal_admin_dashboard()
        self._set_app_feedback(
            f"Inscricoes {'abertas' if self.portal_registrations_open else 'fechadas'} com sucesso.",
            tone="success",
        )

    def _approve_selected_portal_submission(self) -> None:
        if not hasattr(self, "portal_pending_listbox"):
            return
        selection = self.portal_pending_listbox.curselection()
        if not selection:
            self._set_app_feedback("Selecione uma submissao antes de aprovar.", tone="warning")
            return
        submission = self.portal_pending_submissions[selection[0]]
        api_keys = self._ensure_henrik_api_keys()
        if not api_keys:
            self._set_app_feedback("Configure ao menos uma chave da API HenrikDev antes de aprovar times.", tone="warning", persist_ms=7000)
            return
        try:
            self.portal_client.approve_submission(int(submission.get("id", 0)), api_keys)
        except PortalClientError as exc:
            self._set_app_feedback(str(exc), tone="error", persist_ms=7000)
            return

        self._refresh_portal_admin_dashboard()
        self._import_approved_teams_from_portal(show_message=False)
        self._set_app_feedback("Submissao aprovada e times sincronizados com o aplicativo.", tone="success")

    def _reject_selected_portal_submission(self) -> None:
        if not hasattr(self, "portal_pending_listbox"):
            return
        selection = self.portal_pending_listbox.curselection()
        if not selection:
            self._set_app_feedback("Selecione uma submissao antes de recusar.", tone="warning")
            return

        reason = simpledialog.askstring("Portal", "Motivo da recusa:", parent=self)
        if reason is None:
            return

        submission = self.portal_pending_submissions[selection[0]]
        try:
            self.portal_client.reject_submission(int(submission.get("id", 0)), reason)
        except PortalClientError as exc:
            self._set_app_feedback(str(exc), tone="error", persist_ms=7000)
            return

        self._refresh_portal_admin_dashboard()
        self._set_app_feedback("Submissao recusada.", tone="success")

    def _import_approved_teams_from_portal(self, show_message: bool = True) -> None:
        try:
            imported_profiles = self.portal_client.sync_approved_profiles(self._get_team_logo_storage_dir() / "portal")
        except PortalClientError as exc:
            if show_message:
                self._set_app_feedback(str(exc), tone="error", persist_ms=7000)
            return

        total_profiles = len(imported_profiles)
        target_team_count = 4 if total_profiles <= 4 else 8
        profiles = self._get_team_profiles()
        for slot_index in range(8):
            profiles[slot_index] = imported_profiles[slot_index] if slot_index < total_profiles else self._blank_team_profile(slot_index)

        self.state["team_profiles"] = profiles
        self.state["team_count"] = target_team_count
        imported_names = [profile["name"] for profile in imported_profiles if profile.get("name", "").strip()]
        bracket_size = infer_bracket_size(imported_names)
        self.state["match_results"] = {}
        self.state["match_schedule"] = {}
        self.state["selected_match_id"] = ""
        if bracket_size is None:
            self.state["registered_teams"] = []
            self.state["bracket_size"] = target_team_count
        else:
            self.state["registered_teams"] = imported_names
            self.state["bracket_size"] = bracket_size
        self._reset_team_draw_state(save_state=False)
        self._save_state()
        self._populate_widgets_from_state()
        self._refresh_everything(preserve_selected_match=True)
        if show_message:
            self._set_app_feedback("Times aprovados importados com sucesso para o aplicativo.", tone="success")

    def _refresh_portal_users(self) -> None:
        if not hasattr(self, "portal_users_listbox"):
            return
        try:
            self.portal_users = self.portal_client.list_users()
        except PortalClientError as exc:
            self.portal_users = []
            self.portal_users_status_var.set(f"Falha ao carregar usuarios: {exc}")
            self._render_portal_users()
            return

        self.portal_users_status_var.set(f"{len(self.portal_users)} usuario(s) encontrados no portal.")
        self._render_portal_users()

    def _render_portal_users(self) -> None:
        if not hasattr(self, "portal_users_listbox"):
            return
        self.portal_users_listbox.delete(0, "end")
        for item in self.portal_users:
            username = str(item.get("username", "Usuario")).strip() or "Usuario"
            team_payload = item.get("team") if isinstance(item.get("team"), dict) else None
            team_name = str(team_payload.get("name", "")).strip() if team_payload else ""
            suffix = f" | {team_name}" if team_name else ""
            self.portal_users_listbox.insert("end", f"{username}{suffix}")
        if self.portal_users:
            self.portal_users_listbox.selection_set(0)
            self._load_selected_portal_user()
        else:
            self.portal_user_summary_var.set("Nenhum usuario do portal encontrado ainda.")

    def _load_selected_portal_user(self, _event=None) -> None:
        if not hasattr(self, "portal_users_listbox"):
            return
        selection = self.portal_users_listbox.curselection()
        if not selection:
            self.selected_portal_user_id = None
            if hasattr(self, "portal_user_riot_id_var"):
                self.portal_user_riot_id_var.set("")
            self.portal_user_summary_var.set("Selecione um usuario para ver os detalhes.")
            return
        item = self.portal_users[selection[0]]
        self.selected_portal_user_id = int(item.get("id", 0) or 0) or None
        team_payload = item.get("team") if isinstance(item.get("team"), dict) else None
        latest_submission = item.get("latest_submission") if isinstance(item.get("latest_submission"), dict) else None
        if hasattr(self, "portal_user_riot_id_var"):
            self.portal_user_riot_id_var.set(str(item.get("riot_id", "") or ""))
        lines = [
            f"Username: {item.get('username', '-')}",
            f"Nome global: {item.get('global_name', '-') or '-'}",
            f"Discord ID: {item.get('discord_id', '-')}",
            f"Riot ID: {item.get('riot_id', '-') or '-'}",
            f"Entrou em: {item.get('created_at', '-') or '-'}",
            f"Ultima atividade: {item.get('updated_at', '-') or '-'}",
            f"Total de envios: {item.get('submission_count', 0)}",
            f"Time aprovado: {team_payload.get('name', '-') if team_payload else '-'}",
        ]
        if latest_submission:
            lines.extend([
                "",
                f"Ultimo envio: {latest_submission.get('name', '-')}",
                f"Status do envio: {latest_submission.get('status', '-')}",
                f"Enviado em: {latest_submission.get('submitted_at', '-')}",
            ])
        self.portal_user_summary_var.set("\n".join(lines))

    def _save_selected_portal_user_riot_id(self) -> None:
        if not self.selected_portal_user_id:
            self._set_app_feedback("Selecione um usuario antes de salvar o Riot ID.", tone="warning")
            return
        riot_id = str(self.portal_user_riot_id_var.get() if hasattr(self, "portal_user_riot_id_var") else "").strip()
        if not riot_id:
            self._set_app_feedback("Informe um Riot ID no formato Nick#TAG.", tone="warning")
            return
        try:
            self.portal_client.update_user_riot_id(self.selected_portal_user_id, riot_id)
        except PortalClientError as exc:
            self._set_app_feedback(str(exc), tone="error", persist_ms=7000)
            return
        self._refresh_portal_users()
        if self.selected_portal_user_id:
            for index, item in enumerate(self.portal_users):
                if int(item.get("id", 0) or 0) == self.selected_portal_user_id:
                    self.portal_users_listbox.selection_clear(0, "end")
                    self.portal_users_listbox.selection_set(index)
                    self.portal_users_listbox.see(index)
                    self._load_selected_portal_user()
                    break
        self._set_app_feedback("Riot ID do usuario atualizado com sucesso.", tone="success")

    def _load_selected_team_profile(self, _event=None) -> None:
        selection = self.admin_team_slot_listbox.curselection()
        if not selection:
            return
        slot_index = selection[0]
        profile = self._get_team_profiles()[slot_index]
        self.admin_selected_team_var.set(f"Time {slot_index + 1}")
        self.admin_team_name_var.set(profile.get("name", ""))
        self.admin_team_logo_var.set(profile.get("logo_path", ""))
        self.admin_team_coach_var.set(profile.get("coach", ""))
        for index, player_var in enumerate(self.admin_player_vars):
            player_var.set(profile.get("players", ["", "", "", "", ""])[index])
        self._refresh_admin_logo_preview(profile.get("logo_path", ""))

    def _refresh_admin_logo_preview(self, logo_path: str) -> None:
        if not hasattr(self, "admin_logo_preview_label"):
            return
        self.admin_logo_preview = self._load_logo_image(logo_path, max_size=72)
        if self.admin_logo_preview:
            self.admin_logo_preview_label.configure(image=self.admin_logo_preview, text="")
        else:
            self.admin_logo_preview_label.configure(image="", text="Sem logo", fg="#555d66")

    def _choose_team_logo(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Escolher logo do time",
            filetypes=[("Imagens PNG", "*.png"), ("Todas as imagens suportadas", "*.png *.gif *.ppm *.pgm")],
        )
        if not file_path:
            return
        self.admin_team_logo_var.set(file_path)
        self._refresh_admin_logo_preview(file_path)

    def _save_current_team_profile(self) -> None:
        selection = self.admin_team_slot_listbox.curselection()
        if not selection:
            self._set_app_feedback("Selecione um slot de time antes de salvar.", tone="warning")
            return
        slot_index = selection[0]
        profiles = self._get_team_profiles()
        profiles[slot_index] = {
            "slot": slot_index,
            "name": self.admin_team_name_var.get().strip(),
            "logo_path": self.admin_team_logo_var.get().strip(),
            "portal_view_url": profiles[slot_index].get("portal_view_url", ""),
            "coach": self.admin_team_coach_var.get().strip(),
            "players": [player_var.get().strip() for player_var in self.admin_player_vars],
        }
        self.state["team_profiles"] = profiles
        self._save_state()
        self._build_admin_team_editor_cards()
        self._refresh_admin_team_editor_from_state()
        self._refresh_everything(preserve_selected_match=True)
        self._refresh_admin_team_slots()
        self._populate_admin_bracket_from_profiles()
        self.admin_team_editor_feedback_var.set("Time salvo com sucesso.")
        self._set_app_feedback("Time salvo com sucesso.", tone="success")

    def _clear_current_team_profile(self) -> None:
        selection = self.admin_team_slot_listbox.curselection()
        if not selection:
            return
        slot_index = selection[0]
        profiles = self._get_team_profiles()
        profiles[slot_index] = self._blank_team_profile(slot_index)
        self.state["team_profiles"] = profiles
        self._save_state()
        self._refresh_everything(preserve_selected_match=True)
        self._refresh_admin_team_slots()
        self._populate_admin_bracket_from_profiles()

    def _open_team_profile_portal_view(self, slot_index: int) -> None:
        profiles = self._get_team_profiles()
        if slot_index < 0 or slot_index >= len(profiles):
            return
        profile = profiles[slot_index]
        self._open_portal_page(
            str(profile.get("portal_view_url", "")).strip(),
            "Esse time ainda nao tem uma pagina publica no portal. Aprove ou importe um time do backend primeiro.",
        )

    def _handle_team_count_change(self, _event=None) -> None:
        team_count = int(self.team_count_var.get())
        self.state["team_count"] = team_count
        self._reset_team_draw_state(save_state=False)
        if len(self.state.get("registered_teams", [])) != team_count:
            self.state["registered_teams"] = []
            self.state["bracket_size"] = team_count
            self.state["match_results"] = {}
            self.state["match_schedule"] = {}
            self.state["selected_match_id"] = ""
        self._save_state()
        self._build_admin_team_editor_cards()
        self._refresh_admin_team_editor_from_state()
        self._refresh_everything(preserve_selected_match=True)
        self._refresh_admin_team_slots()
        self._populate_admin_bracket_from_profiles()

    def _populate_admin_bracket_from_profiles(self) -> None:
        if not hasattr(self, "admin_bracket_teams_text"):
            return
        team_names = [profile["name"] for profile in self._get_active_team_profiles() if profile.get("name", "").strip()]
        self.admin_bracket_teams_text.delete("1.0", "end")
        self.admin_bracket_teams_text.insert("1.0", "\n".join(team_names))

    def _populate_match_schedule_editor(self) -> None:
        if not hasattr(self, "match_schedule_text"):
            return
        bracket_size = int(self.state.get("bracket_size", 4))
        template = get_bracket_template(bracket_size)
        existing_schedule = self.state.get("match_schedule", {}) if isinstance(self.state.get("match_schedule", {}), dict) else {}
        lines = [f"{match['id']} = {existing_schedule.get(match['id'], '')}".rstrip() for match in template]
        self.match_schedule_text.delete("1.0", "end")
        self.match_schedule_text.insert("1.0", "\n".join(lines))

    def _save_match_schedule(self) -> None:
        if not hasattr(self, "match_schedule_text"):
            return
        bracket_size = int(self.state.get("bracket_size", 4))
        valid_match_ids = {match["id"] for match in get_bracket_template(bracket_size)}
        parsed_schedule: dict[str, str] = {}
        invalid_lines: list[str] = []
        for raw_line in self.match_schedule_text.get("1.0", "end").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "=" in line:
                match_id, date_value = line.split("=", 1)
            elif ":" in line:
                match_id, date_value = line.split(":", 1)
            else:
                invalid_lines.append(line)
                continue
            match_id = match_id.strip().upper()
            date_value = date_value.strip()
            if match_id not in valid_match_ids:
                invalid_lines.append(line)
                continue
            parsed_schedule[match_id] = date_value

        self.state["match_schedule"] = parsed_schedule
        self._save_state()
        self._refresh_everything(preserve_selected_match=True)
        self._populate_match_schedule_editor()
        if invalid_lines:
            messagebox.showwarning("Chave", "Algumas linhas foram ignoradas por estarem fora do formato esperado:\n\n" + "\n".join(invalid_lines))
        else:
            self._set_app_feedback("Datas da chave salvas com sucesso.", tone="success")

    def _apply_panel_teams_to_bracket(self) -> None:
        team_names = [profile["name"].strip() for profile in self._get_active_team_profiles() if profile.get("name", "").strip()]
        bracket_size = infer_bracket_size(team_names)
        if bracket_size is None or len(team_names) != int(self.state.get("team_count", 4)):
            messagebox.showwarning("Painel", "Preencha corretamente os nomes dos 4 ou 8 times ativos antes de aplicar na chave.")
            return

        current_teams = self.state.get("registered_teams", [])
        if current_teams != team_names:
            self.state["match_results"] = {}
        self.state["registered_teams"] = team_names
        self.state["bracket_size"] = bracket_size
        self.state["selected_match_id"] = ""
        self._save_state()
        self._refresh_everything()
        self._populate_admin_bracket_from_profiles()
        self._select_tab(3)

    def _handle_window_map(self, _event=None) -> None:
        if tk.Tk.state(self) != "iconic":
            self.after(10, self._apply_window_style)

    def _minimize_window(self) -> None:
        self.update_idletasks()
        self.iconify()

    def _show_initial_window(self) -> None:
        self.deiconify()
        self._apply_window_style()
        self.lift()
        self.wm_attributes("-alpha", 1.0)
        self.is_maximized = False
        self._update_mode_button()

    def _apply_window_style(self) -> None:
        if sys.platform != "win32":
            return

        try:
            self.update_idletasks()
            handles = self._get_window_handles()
            if handles:
                self.native_hwnd = handles[-1]
            for hwnd in handles:
                current_style = ctypes.windll.user32.GetWindowLongW(hwnd, self.GWL_STYLE)
                current_exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, self.GWL_EXSTYLE)
                borderless_style = current_style | self.WS_MINIMIZEBOX | self.WS_MAXIMIZEBOX | self.WS_SYSMENU
                borderless_style &= ~(self.WS_CAPTION | self.WS_THICKFRAME)
                updated_style = (current_exstyle | self.WS_EX_APPWINDOW) & ~self.WS_EX_TOOLWINDOW
                ctypes.windll.user32.SetWindowLongW(hwnd, self.GWL_STYLE, borderless_style)
                ctypes.windll.user32.SetWindowLongW(hwnd, self.GWL_EXSTYLE, updated_style)
                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    0,
                    0,
                    0,
                    0,
                    0,
                    self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_NOZORDER | self.SWP_FRAMECHANGED,
                )
        except Exception:
            return

    def _get_window_handles(self) -> list[int]:
        if sys.platform != "win32":
            return []

        handles: list[int] = []
        seen: set[int] = set()
        direct_handle = self.winfo_id()
        parent_handle = ctypes.windll.user32.GetParent(direct_handle)
        root_handle = ctypes.windll.user32.GetAncestor(direct_handle, self.GA_ROOT)

        for hwnd in (direct_handle, parent_handle, root_handle):
            if hwnd and hwnd not in seen:
                handles.append(hwnd)
                seen.add(hwnd)
        return handles

    def _maximize_window(self) -> None:
        if not self.is_maximized:
            self.restore_geometry = self.geometry()
        self._apply_maximized_geometry()
        self.is_maximized = True
        self._update_mode_button()
        self.after_idle(self._apply_window_style)
        self.after(20, self._apply_maximized_geometry)

    def _restore_window(self) -> None:
        if self.restore_geometry:
            self.geometry(self.restore_geometry)
        self.is_maximized = False
        self._update_mode_button()
        self.after_idle(self._apply_window_style)

    def _toggle_maximize(self) -> None:
        if self.is_maximized:
            self._restore_window()
        else:
            self._maximize_window()

    def _get_window_work_area(self) -> dict[str, int]:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        if sys.platform != "win32":
            return {"x": 0, "y": 0, "width": screen_width, "height": screen_height}

        hwnd = self.native_hwnd or self.winfo_id()
        monitor_handle = ctypes.windll.user32.MonitorFromWindow(hwnd, self.MONITOR_DEFAULTTONEAREST)

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        monitor_info = MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
        if ctypes.windll.user32.GetMonitorInfoW(monitor_handle, ctypes.byref(monitor_info)):
            work_rect = monitor_info.rcWork
            return {
                "x": int(work_rect.left),
                "y": int(work_rect.top),
                "width": int(work_rect.right - work_rect.left),
                "height": int(work_rect.bottom - work_rect.top),
            }
        return {"x": 0, "y": 0, "width": screen_width, "height": screen_height}

    def _apply_maximized_geometry(self) -> None:
        work_area = self._get_window_work_area()
        self.geometry(f"{work_area['width']}x{work_area['height']}+{work_area['x']}+{work_area['y']}")

        if sys.platform != "win32":
            return

        self.update_idletasks()
        hwnd = self.native_hwnd or self.winfo_id()

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rect = RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return

        work_left = work_area["x"]
        work_top = work_area["y"]
        work_right = work_left + work_area["width"]
        work_bottom = work_top + work_area["height"]

        overflow_left = max(work_left - int(rect.left), 0)
        overflow_top = max(work_top - int(rect.top), 0)
        overflow_right = max(int(rect.right) - work_right, 0)
        overflow_bottom = max(int(rect.bottom) - work_bottom, 0)

        if not any((overflow_left, overflow_top, overflow_right, overflow_bottom)):
            return

        adjusted_x = work_left + overflow_left
        adjusted_y = work_top + overflow_top
        adjusted_width = max(960, work_area["width"] - overflow_left - overflow_right)
        adjusted_height = max(640, work_area["height"] - overflow_top - overflow_bottom)
        self.geometry(f"{adjusted_width}x{adjusted_height}+{adjusted_x}+{adjusted_y}")

    def _update_mode_button(self) -> None:
        if self.is_maximized:
            self.maximize_button.default_bg = "#1b1b1b"
            self.maximize_button.configure(text="[]", bg="#1b1b1b")
        else:
            self.maximize_button.default_bg = "#070707"
            self.maximize_button.configure(text="[ ]", bg="#070707")

    def _begin_native_drag(self, _event=None) -> None:
        if self.is_maximized or not self.native_hwnd or sys.platform != "win32":
            return
        ctypes.windll.user32.ReleaseCapture()
        ctypes.windll.user32.SendMessageW(self.native_hwnd, self.WM_NCLBUTTONDOWN, self.HTCAPTION, 0)
        self.after_idle(self._sync_restore_geometry)

    def _begin_native_resize(self, hit_target: int) -> None:
        if self.is_maximized or not self.native_hwnd or sys.platform != "win32":
            return
        ctypes.windll.user32.ReleaseCapture()
        ctypes.windll.user32.SendMessageW(self.native_hwnd, self.WM_NCLBUTTONDOWN, hit_target, 0)
        self.after_idle(self._sync_restore_geometry)

    def _sync_restore_geometry(self) -> None:
        if not self.is_maximized:
            self.restore_geometry = self.geometry()

    def _redraw_home_screen(self, _event=None) -> None:
        width = max(self.home_canvas.winfo_width(), 1)
        height = max(self.home_canvas.winfo_height(), 1)
        self.home_canvas.delete("home-bg")
        self.home_canvas.delete("home-logo")
        self.logo_item = None

        self._draw_home_gradient(width, height)
        self._draw_home_logo(width, height)
        self._layout_home_buttons(width, height)
        self.home_canvas.tag_raise("home-menu")

    def _draw_home_gradient(self, width: int, height: int) -> None:
        start_rgb = (6, 6, 7)
        end_rgb = (26, 26, 28)
        for y in range(height):
            ratio = y / max(height - 1, 1)
            red = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * ratio)
            green = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * ratio)
            blue = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * ratio)
            color = f"#{red:02x}{green:02x}{blue:02x}"
            self.home_canvas.create_line(0, y, width, y, fill=color, tags="home-bg")

        self.home_canvas.create_rectangle(24, 24, width - 24, height - 24, outline="", fill="#101011", tags="home-bg")
        self.home_canvas.create_rectangle(60, 60, width - 60, height - 60, outline="", fill="#0d0d0e", stipple="gray25", tags="home-bg")

    def _draw_home_logo(self, width: int, height: int) -> None:
        if not self.logo_source:
            self.home_canvas.create_text(
                width * 0.25,
                height * 0.44,
                text="VCT DA\nRESENHA",
                fill="#f3f3f3",
                anchor="center",
                justify="left",
                font=(self.button_font_family, 88),
                tags="home-logo",
            )
            return

        target_width = max(int(width * 0.40), 420)
        source_width = max(self.logo_source.width(), 1)
        scale = max(1, (source_width + target_width - 1) // target_width)
        if self.logo_image is None or scale != self.last_logo_scale:
            self.logo_image = self.logo_source.subsample(scale, scale)
            self.last_logo_scale = scale

        if self.logo_item is None:
            self.logo_item = self.home_canvas.create_image(0, 0, image=self.logo_image, anchor="center", tags="home-logo")
        else:
            self.home_canvas.itemconfigure(self.logo_item, image=self.logo_image)

        self.home_canvas.coords(self.logo_item, width * 0.285, height * 0.49)

    def _layout_home_buttons(self, width: int, height: int) -> None:
        start_x = width * 0.69
        start_y = height * 0.24
        gap = max(int(height * 0.108), 86)
        underline_length = min(int(width * 0.075), 150)

        for index, (label, _tab_index) in enumerate(self.home_button_specs):
            button_info = self.home_button_items[label]
            text_y = start_y + index * gap
            self.home_canvas.coords(button_info["text_id"], start_x, text_y)
            bbox = self.home_canvas.bbox(button_info["text_id"])
            if bbox:
                underline_y = bbox[3] + 8
                self.home_canvas.coords(
                    button_info["underline_id"],
                    bbox[0],
                    underline_y,
                    bbox[0] + underline_length,
                    underline_y,
                )

    def _set_home_hover(self, label: str, hovered: bool) -> None:
        button_info = self.home_button_items[label]
        self.home_canvas.itemconfigure(button_info["underline_id"], state="normal" if hovered else "hidden")
        self.home_canvas.itemconfigure(button_info["text_id"], fill="#ffffff" if hovered else "#f3f3f3")

    def _set_content_nav_hover(self, index: int, hovered: bool) -> None:
        if index == self.current_tab_index:
            return
        nav_item = self.content_nav_items[index]
        nav_item["button"].configure(fg="#f3f3f3" if hovered else "#8a8f98")

    def _set_active_content_nav(self, index: int) -> None:
        for nav_index, nav_item in self.content_nav_items.items():
            is_active = nav_index == index
            nav_item["button"].configure(fg="#f3f3f3" if is_active else "#8a8f98")
            nav_item["underline"].configure(bg="#f3f3f3" if is_active else "#111214")

    def _show_home_screen(self) -> None:
        self.home_is_visible = True
        self.content_view.place_forget()
        self.home_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._update_back_button_state()
        self.after_idle(self._redraw_home_screen)

    def _show_content_view(self) -> None:
        self.home_is_visible = False
        self.home_view.place_forget()
        self.content_view.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._update_back_button_state()
        self._set_active_content_nav(self.current_tab_index)

    def _open_section(self, index: int) -> None:
        if index == 0:
            self._open_panel_window()
            return
        self._show_content_view()
        self.notebook.select(self.tab_frames[index])
        self.current_tab_index = index
        self._set_active_content_nav(index)
        self._update_back_button_state()

    def _build_cards_tab(self) -> None:
        self.cards_tab.columnconfigure(0, weight=1)
        self.cards_tab.columnconfigure(1, weight=1)
        self.cards_tab.rowconfigure(0, weight=1)

        pool_frame = ttk.LabelFrame(self.cards_tab, text="Pool de cartas", padding=16)
        pool_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        pool_frame.columnconfigure(0, weight=1)
        pool_frame.rowconfigure(1, weight=1)

        ttk.Label(pool_frame, text="Uma carta por linha.", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.cards_text = tk.Text(pool_frame, height=18, wrap="word", relief="flat", padx=12, pady=12)
        self.cards_text.grid(row=1, column=0, sticky="nsew")

        cards_actions = ttk.Frame(pool_frame)
        cards_actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        cards_actions.columnconfigure((0, 1, 2), weight=1)

        ttk.Button(cards_actions, text="Salvar pool", style="Primary.TButton", command=self._save_cards_pool).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(cards_actions, text="Sortear proxima carta", style="Primary.TButton", command=self._draw_next_card).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(cards_actions, text="Resetar sorteio", command=self._reset_card_draw).grid(
            row=0, column=2, sticky="ew", padx=(8, 0)
        )

        result_frame = ttk.LabelFrame(self.cards_tab, text="Resultado do sorteio", padding=16)
        result_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(2, weight=1)

        ttk.Label(result_frame, text="Ultima carta sorteada", style="Section.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.current_card_value = ttk.Label(result_frame, text="Nenhuma carta sorteada ainda.")
        self.current_card_value.grid(row=1, column=0, sticky="w", pady=(8, 16))

        ttk.Label(result_frame, text="Historico", style="Section.TLabel").grid(row=2, column=0, sticky="nw")
        self.drawn_cards_list = tk.Listbox(result_frame, activestyle="none", borderwidth=0, highlightthickness=0)
        self.drawn_cards_list.grid(row=3, column=0, sticky="nsew", pady=(8, 0))

    def _build_teams_tab(self) -> None:
        _shell, _canvas, content = self._create_scrollable_container(self.teams_tab, bg="#0b0b0c", show_scrollbar=False)

        self.teams_public_grid = tk.Frame(content, bg="#0b0b0c", padx=10, pady=14)
        self.teams_public_grid.grid(row=0, column=0, sticky="nsew")
        for column_index in range(4):
            self.teams_public_grid.columnconfigure(column_index, weight=1)

    def _show_public_team_draw_view(self) -> None:
        self.public_teams_mode = "draw"
        self._refresh_teams_tree()

    def _show_public_team_list_view(self) -> None:
        self.public_teams_mode = "list"
        self._refresh_teams_tree()

    def _show_public_team_menu_view(self) -> None:
        self.public_teams_mode = "menu"
        self._refresh_teams_tree()

    def _build_public_team_mode_buttons(self, parent: tk.Widget) -> None:
        actions = tk.Frame(parent, bg="#0b0b0c")
        actions.pack(anchor="center", pady=(12, 12))
        button_specs = [
            ("SORTEAR TIMES", self._show_public_team_draw_view, self.public_teams_mode == "draw"),
            ("VER TIMES", self._show_public_team_list_view, self.public_teams_mode == "list"),
        ]
        for label, command, is_active in button_specs:
            tk.Button(
                actions,
                text=label,
                command=command,
                relief="flat",
                borderwidth=0,
                bg="#efefef" if is_active else "#1a1c20",
                fg="#050607" if is_active else "#f3efec",
                activebackground="#ffffff" if is_active else "#262a30",
                activeforeground="#050607" if is_active else "#ffffff",
                cursor="hand2",
                font=(self.button_font_family, 20),
                padx=28,
                pady=10,
            ).pack(side="left", padx=8)

    def _build_public_teams_menu_view(self) -> None:
        wrapper = tk.Frame(self.teams_public_grid, bg="#0b0b0c")
        wrapper.grid(row=0, column=0, columnspan=4, sticky="nsew")
        wrapper.columnconfigure(0, weight=1)
        wrapper.rowconfigure(0, weight=1)

        panel = tk.Frame(wrapper, bg="#111214", highlightthickness=1, highlightbackground="#23262b", padx=40, pady=42)
        panel.grid(row=0, column=0, padx=38, pady=34)
        tk.Label(panel, text="TIMES DA RESENHA", bg="#111214", fg="#f3efec", font=(self.button_font_family, 34)).pack(anchor="center")
        tk.Label(
            panel,
            text="Escolha se voce quer sortear os confrontos ou apenas visualizar os times cadastrados.",
            bg="#111214",
            fg="#a6adb7",
            font=(self.title_font_family, 11),
            justify="center",
        ).pack(anchor="center", pady=(12, 0))
        self._build_public_team_mode_buttons(panel)

    def _build_public_team_draw_view(self) -> None:
        profiles = self._get_active_draw_profiles()
        wrapper = tk.Frame(self.teams_public_grid, bg="#0b0b0c")
        wrapper.grid(row=0, column=0, columnspan=4, sticky="nsew")
        wrapper.columnconfigure(0, weight=1)

        self._build_public_team_mode_buttons(wrapper)

        if len(profiles) not in SUPPORTED_BRACKET_SIZES:
            warning_card = tk.Frame(wrapper, bg="#16171a", highlightthickness=1, highlightbackground="#292c31", padx=26, pady=26)
            warning_card.pack(fill="x", padx=28, pady=(18, 0))
            tk.Label(warning_card, text="SORTEIO DE TIMES", bg="#16171a", fg="#f3f3f3", font=(self.button_font_family, 32)).pack(anchor="center")
            tk.Label(
                warning_card,
                text="Cadastre exatamente 4 ou 8 times ativos no Painel para liberar o sorteio dos confrontos.",
                bg="#16171a",
                fg="#b0b6be",
                justify="center",
                font=(self.title_font_family, 11),
            ).pack(anchor="center", pady=(12, 0))
            return

        draw_state = self._get_team_draw_state()
        current_pair_slots = draw_state.get("current_pair", [])[:2]
        slot_lookup = self._get_draw_slot_to_profile()
        current_pair = [slot_lookup.get(slot, self._blank_team_profile(slot)) for slot in current_pair_slots]
        while len(current_pair) < 2:
            current_pair.append(self._blank_team_profile(len(current_pair)))

        title_wrap = tk.Frame(wrapper, bg="#0b0b0c")
        title_wrap.pack(fill="x", pady=(8, 0))
        tk.Label(title_wrap, text="SORTEIO DE TIMES", bg="#0b0b0c", fg="#f4ede8", font=(self.button_font_family, 36)).pack(anchor="center")

        arena = tk.Frame(wrapper, bg="#1b1413", highlightthickness=1, highlightbackground="#342625", padx=30, pady=34)
        arena.pack(fill="x", padx=46, pady=(20, 0))
        arena.columnconfigure((0, 2), weight=1)

        self.team_draw_left_name_var = tk.StringVar(value=current_pair[0].get("name", "Aguardando"))
        self.team_draw_right_name_var = tk.StringVar(value=current_pair[1].get("name", "Aguardando"))
        self.team_draw_left_logo_label = None
        self.team_draw_right_logo_label = None
        self.team_draw_pair_feedback_var = tk.StringVar(value=self._get_public_draw_feedback_text())

        self._build_public_draw_card(arena, 0, current_pair[0], side="left")
        arena.configure(bg="#111214", highlightbackground="#24272d")
        tk.Label(arena, text="VS", bg="#111214", fg="#5f6670", font=(self.button_font_family, 34)).grid(row=0, column=1, padx=30)
        self._build_public_draw_card(arena, 2, current_pair[1], side="right")

        tk.Label(wrapper, textvariable=self.team_draw_pair_feedback_var, bg="#0b0b0c", fg="#c9beb9", font=(self.title_font_family, 11, "bold")).pack(anchor="center", pady=(18, 0))

        actions = tk.Frame(wrapper, bg="#0b0b0c")
        actions.pack(anchor="center", pady=(18, 0))
        main_button_text = "FINALIZAR SORTEIO" if len(draw_state.get("draw_order", [])) == len(profiles) and profiles else "SORTEAR"
        tk.Button(
            actions,
            text="SORTEAR",
            command=self._handle_public_team_draw_action,
            relief="flat",
            borderwidth=0,
            bg="#efefef",
            fg="#050607",
            activebackground="#ffffff",
            activeforeground="#050607",
            cursor="hand2",
            font=(self.button_font_family, 22),
            padx=42,
            pady=10,
            state="disabled" if draw_state.get("is_finalized") else "normal",
        ).pack(side="left", padx=8)
        tk.Button(
            actions,
            text="REINICIAR",
            command=self._reset_public_team_draw_and_refresh,
            relief="flat",
            borderwidth=0,
            bg="#1a1c20",
            fg="#f6f1ee",
            activebackground="#262a30",
            activeforeground="#ffffff",
            cursor="hand2",
            font=(self.button_font_family, 18),
            padx=26,
            pady=10,
        ).pack(side="left", padx=8)

        if draw_state.get("is_finalized") and profiles:
            tk.Button(
                wrapper,
                text="VER CHAVE",
                command=self._open_bracket_from_team_draw,
                relief="flat",
                borderwidth=0,
                bg="#f3f3f3",
                fg="#050607",
                activebackground="#ffffff",
                activeforeground="#000000",
                cursor="hand2",
                font=(self.button_font_family, 18),
                padx=28,
                pady=10,
            ).pack(anchor="center", pady=(14, 0))

    def _build_public_draw_card(self, parent: tk.Widget, column_index: int, profile: dict, side: str) -> None:
        card = tk.Frame(parent, bg="#17191d", highlightthickness=1, highlightbackground="#2d3138", padx=20, pady=20)
        card.grid(row=0, column=column_index, sticky="ew", padx=18)
        card.columnconfigure(0, weight=1)
        logo_wrap = tk.Frame(card, bg="#eef0f2", width=96, height=96)
        logo_wrap.grid(row=0, column=0, pady=(0, 14))
        logo_wrap.pack_propagate(False)
        logo_image = self._load_logo_image(profile.get("logo_path", ""), max_size=96)
        if logo_image:
            self.public_team_logo_refs.append(logo_image)
            label = tk.Label(logo_wrap, image=logo_image, bg="#eef0f2")
            label.pack(fill="both", expand=True)
        else:
            label = tk.Label(logo_wrap, text=(profile.get("name", "?")[:2] or "??").upper(), bg="#eef0f2", fg="#111214", font=(self.button_font_family, 24))
            label.pack(fill="both", expand=True)
        if side == "left":
            self.team_draw_left_logo_label = label
        else:
            self.team_draw_right_logo_label = label

        name_label = tk.Label(card, textvariable=self.team_draw_left_name_var if side == "left" else self.team_draw_right_name_var, bg="#17191d", fg="#f3efec", font=(self.button_font_family, 28))
        name_label.grid(row=1, column=0, sticky="ew")

    def _get_public_draw_pairs(self) -> list[list[dict]]:
        slot_lookup = self._get_draw_slot_to_profile()
        draw_order = self._get_team_draw_state().get("draw_order", [])
        pairs: list[list[dict]] = []
        for index in range(0, len(draw_order), 2):
            pair_slots = draw_order[index:index + 2]
            if len(pair_slots) == 2 and all(slot in slot_lookup for slot in pair_slots):
                pairs.append([slot_lookup[pair_slots[0]], slot_lookup[pair_slots[1]]])
        return pairs

    def _get_public_draw_feedback_text(self) -> str:
        profiles = self._get_active_draw_profiles()
        draw_state = self._get_team_draw_state()
        if not profiles:
            return "Cadastre os times no Painel para liberar o sorteio."
        if draw_state.get("is_finalized"):
            return "Sorteio concluido. A chave e as partidas ja foram atualizadas automaticamente."
        pair_count = len(draw_state.get("draw_order", [])) // 2
        total_pairs = len(profiles) // 2
        return f"Confrontos definidos: {pair_count}/{total_pairs}"

    def _handle_public_team_draw_action(self) -> None:
        draw_state = self._get_team_draw_state()
        if draw_state.get("is_finalized"):
            return
        self._start_public_team_draw()

    def _start_public_team_draw(self) -> None:
        if self.team_draw_animation_active:
            return
        slot_lookup = self._get_draw_slot_to_profile()
        draw_state = self._get_team_draw_state()
        remaining_slots = [slot for slot in slot_lookup if slot not in draw_state.get("draw_order", [])]
        if len(remaining_slots) < 2:
            return
        selected_slots = random.sample(remaining_slots, 2)
        self.team_draw_animation_active = True

        steps = 16
        available_slots = remaining_slots[:]

        def animate(step_index: int) -> None:
            if step_index >= steps:
                self.team_draw_animation_active = False
                self._commit_public_draw_pair(selected_slots)
                return
            preview_slots = random.sample(available_slots, 2)
            self._update_public_draw_card_pair(preview_slots)
            job_id = self.after(85 + (step_index * 4), lambda: animate(step_index + 1))
            self.team_draw_animation_jobs.append(job_id)

        animate(0)

    def _update_public_draw_card_pair(self, slot_pair: list[int]) -> None:
        slot_lookup = self._get_draw_slot_to_profile()
        pair_profiles = [slot_lookup.get(slot, self._blank_team_profile(slot)) for slot in slot_pair[:2]]
        while len(pair_profiles) < 2:
            pair_profiles.append(self._blank_team_profile(len(pair_profiles)))
        self.team_draw_left_name_var.set(pair_profiles[0].get("name", "Aguardando"))
        self.team_draw_right_name_var.set(pair_profiles[1].get("name", "Aguardando"))
        self._refresh_public_draw_logo_label(self.team_draw_left_logo_label, pair_profiles[0])
        self._refresh_public_draw_logo_label(self.team_draw_right_logo_label, pair_profiles[1])

    def _refresh_public_draw_logo_label(self, label: tk.Label | None, profile: dict) -> None:
        if not label:
            return
        logo_image = self._load_logo_image(profile.get("logo_path", ""), max_size=96)
        if logo_image:
            self.public_team_logo_refs.append(logo_image)
            label.configure(image=logo_image, text="")
            label.image = logo_image
        else:
            label.configure(image="", text=(profile.get("name", "?")[:2] or "??").upper(), fg="#1a1413")
            label.image = None

    def _commit_public_draw_pair(self, selected_slots: list[int]) -> None:
        draw_state = self._get_team_draw_state()
        draw_state["current_pair"] = selected_slots[:2]
        draw_state["draw_order"].extend(selected_slots[:2])
        draw_state["is_finalized"] = False
        self._save_state()
        if len(draw_state.get("draw_order", [])) == len(self._get_active_draw_profiles()):
            self._finalize_public_team_draw()
            return
        self._refresh_teams_tree()

    def _reset_public_team_draw_and_refresh(self) -> None:
        for job_id in self.team_draw_animation_jobs:
            try:
                self.after_cancel(job_id)
            except Exception:
                pass
        self.team_draw_animation_jobs = []
        self.team_draw_animation_active = False
        self._reset_team_draw_state(save_state=True)
        self._refresh_teams_tree()

    def _finalize_public_team_draw(self) -> None:
        draw_state = self._get_team_draw_state()
        active_profiles = self._get_active_draw_profiles()
        draw_order = draw_state.get("draw_order", [])
        if len(draw_order) != len(active_profiles):
            messagebox.showwarning("Sorteio", "Defina todos os confrontos antes de finalizar o sorteio.")
            return

        seeded_team_names = self._build_seeded_team_names_from_draw(draw_order)
        if not seeded_team_names:
            messagebox.showwarning("Sorteio", "Nao foi possivel converter o sorteio em confrontos da chave.")
            return

        current_teams = self.state.get("registered_teams", [])
        if current_teams != seeded_team_names:
            self.state["match_results"] = {}
            self.state["match_schedule"] = {}

        self.state["registered_teams"] = seeded_team_names
        self.state["bracket_size"] = len(seeded_team_names)
        self.state["selected_match_id"] = ""
        draw_state["is_finalized"] = True
        self._save_state()
        self._refresh_everything()
        self._populate_admin_bracket_from_profiles()
        self._refresh_teams_tree()

    def _build_seeded_team_names_from_draw(self, draw_order: list[int]) -> list[str]:
        slot_lookup = self._get_draw_slot_to_profile()
        team_names = [slot_lookup[slot].get("name", "").strip() for slot in draw_order if slot in slot_lookup]
        if len(team_names) == 4:
            return [team_names[0], team_names[2], team_names[3], team_names[1]]
        if len(team_names) == 8:
            return [team_names[0], team_names[4], team_names[6], team_names[2], team_names[3], team_names[7], team_names[5], team_names[1]]
        return []

    def _open_bracket_from_team_draw(self) -> None:
        draw_state = self._get_team_draw_state()
        if not draw_state.get("is_finalized"):
            self._finalize_public_team_draw()
        self._select_tab(3)

    def _render_public_team_list_view(self) -> None:
        wrapper = tk.Frame(self.teams_public_grid, bg="#0b0b0c")
        wrapper.grid(row=0, column=0, columnspan=4, sticky="nsew")
        wrapper.columnconfigure((0, 1, 2, 3), weight=1)

        self._build_public_team_mode_buttons(wrapper)

        title_label = tk.Label(wrapper, text="TIMES DA RESENHA", bg="#0b0b0c", fg="#f3f3f3", font=(self.button_font_family, 30))
        title_label.pack(anchor="center", pady=(8, 18))

        profiles = [profile for profile in self._get_active_team_profiles() if profile.get("name", "").strip()]
        if not profiles:
            placeholder = tk.Frame(wrapper, bg="#111214", padx=24, pady=24)
            placeholder.pack(fill="x", padx=12, pady=12)
            tk.Label(placeholder, text="Nenhum time cadastrado ainda.", bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 22)).pack(anchor="w")
            tk.Label(placeholder, text="Use o Painel para criar os times com logo, coach e jogadores.", bg="#111214", fg="#8a8f98", font=(self.title_font_family, 10)).pack(anchor="w", pady=(6, 0))
            return

        cards_grid = tk.Frame(wrapper, bg="#0b0b0c")
        cards_grid.pack(fill="both", expand=True)
        for column_index in range(4):
            cards_grid.columnconfigure(column_index, weight=1)

        for index, profile in enumerate(profiles):
            card = tk.Frame(cards_grid, bg="#121417", highlightthickness=1, highlightbackground="#262a30", padx=16, pady=16)
            card.grid(row=index // 4, column=index % 4, sticky="nsew", padx=10, pady=10)
            cards_grid.rowconfigure(index // 4, weight=1)
            card.columnconfigure(0, weight=1)

            top = tk.Frame(card, bg="#121417")
            top.pack(fill="x")
            logo_container = tk.Frame(top, bg="#eef0f2", width=78, height=78)
            logo_container.pack(side="left", padx=(0, 14))
            logo_container.pack_propagate(False)
            logo_image = self._load_logo_image(profile.get("logo_path", ""), max_size=72)
            if logo_image:
                self.public_team_logo_refs.append(logo_image)
                tk.Label(logo_container, image=logo_image, bg="#eef0f2").pack(fill="both", expand=True)
            else:
                initials = (profile.get("name", "TS")[:2] or "TS").upper()
                tk.Label(logo_container, text=initials, bg="#eef0f2", fg="#121417", font=(self.button_font_family, 20)).pack(fill="both", expand=True)

            title_block = tk.Frame(top, bg="#121417")
            title_block.pack(side="left", fill="x", expand=True)
            tk.Label(title_block, text=profile.get("name", "Time"), bg="#121417", fg="#f3f3f3", anchor="w", font=(self.button_font_family, 20)).pack(fill="x")
            meta_row = tk.Frame(title_block, bg="#121417")
            meta_row.pack(fill="x", pady=(8, 0))
            tk.Label(meta_row, text="COACH", bg="#1e2228", fg="#c8d0da", padx=8, pady=4, font=(self.title_font_family, 9, "bold")).pack(side="left")
            tk.Label(meta_row, text=profile.get('coach', '') or '-', bg="#121417", fg="#9ca3ad", anchor="w", font=(self.title_font_family, 10, "bold")).pack(side="left", padx=(10, 0))

            lineup_card = tk.Frame(card, bg="#0d0f12", highlightthickness=1, highlightbackground="#20242a", padx=12, pady=12)
            lineup_card.pack(fill="both", expand=True, pady=(16, 0))
            tk.Label(lineup_card, text="LINEUP", bg="#0d0f12", fg="#f1f3f5", anchor="w", font=(self.button_font_family, 18)).pack(fill="x")
            for player_index, player in enumerate(profile.get("players", [])):
                if player.strip():
                    row = tk.Frame(lineup_card, bg="#14181d", padx=10, pady=8)
                    row.pack(fill="x", pady=(10 if player_index == 0 else 6, 0))
                    prefix = "★ CAPITAO" if player_index == 0 else f"JOGADOR {player_index + 1}"
                    tk.Label(row, text=prefix, bg="#14181d", fg="#9ca6b2", width=12, anchor="w", font=(self.title_font_family, 8, "bold")).pack(side="left")
                    tk.Label(row, text=player, bg="#14181d", fg="#f3f3f3", anchor="w", font=(self.title_font_family, 10, "bold")).pack(side="left", fill="x", expand=True, padx=(8, 0))

    def _build_admin_teams_tab(self) -> None:
        self.admin_teams_tab.columnconfigure(0, weight=1)
        self.admin_teams_tab.rowconfigure(1, weight=1)

        self._ensure_admin_team_form_state()

        top_bar = tk.Frame(self.admin_teams_tab, bg="#0b0b0c")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        top_bar.columnconfigure(4, weight=1)

        tk.Label(top_bar, text="MONTAGEM DOS TIMES", bg="#0b0b0c", fg="#f3f3f3", font=(self.button_font_family, 24)).grid(row=0, column=0, sticky="w")
        tk.Label(top_bar, text="Times ativos", bg="#0b0b0c", fg="#c6ccd3", font=(self.title_font_family, 10, "bold")).grid(row=0, column=1, sticky="e", padx=(18, 8))
        self.team_count_var = tk.StringVar(value=str(self.state.get("team_count", 4)))
        self.team_count_combo = ttk.Combobox(top_bar, width=8, state="readonly", textvariable=self.team_count_var, values=[str(size) for size in SUPPORTED_BRACKET_SIZES])
        self.team_count_combo.grid(row=0, column=2, sticky="w")
        self.team_count_combo.bind("<<ComboboxSelected>>", self._handle_team_count_change)
        ttk.Button(top_bar, text="Salvar todos os times", style="Primary.TButton", command=self._save_all_team_profiles).grid(row=0, column=3, sticky="ew", padx=(16, 0))
        self.admin_team_editor_feedback_var = tk.StringVar(value="Monte os times aqui. Esta aba nao aplica nada direto na chave.")
        tk.Label(top_bar, textvariable=self.admin_team_editor_feedback_var, bg="#0b0b0c", fg="#a2a8b0", anchor="e", font=(self.title_font_family, 10)).grid(row=0, column=4, sticky="ew", padx=(18, 0))

        editor_shell = tk.Frame(self.admin_teams_tab, bg="#111214", highlightthickness=1, highlightbackground="#1f2125")
        editor_shell.grid(row=1, column=0, sticky="nsew")
        editor_shell.columnconfigure(0, weight=1)
        editor_shell.rowconfigure(0, weight=1)

        self.admin_team_canvas = tk.Canvas(editor_shell, bg="#111214", highlightthickness=0, bd=0)
        self.admin_team_canvas.grid(row=0, column=0, sticky="nsew")
        admin_scrollbar = ttk.Scrollbar(editor_shell, orient="vertical", command=self.admin_team_canvas.yview)
        admin_scrollbar.grid(row=0, column=1, sticky="ns")
        self.admin_team_canvas.configure(yscrollcommand=admin_scrollbar.set)
        self._register_mousewheel_route(editor_shell, self.admin_team_canvas)
        self._register_mousewheel_route(self.admin_team_canvas, self.admin_team_canvas)

        self.admin_team_cards_frame = tk.Frame(self.admin_team_canvas, bg="#111214", padx=16, pady=16)
        self.admin_team_canvas_window = self.admin_team_canvas.create_window((0, 0), window=self.admin_team_cards_frame, anchor="nw")
        self.admin_team_cards_frame.bind("<Configure>", lambda _event: self.admin_team_canvas.configure(scrollregion=self.admin_team_canvas.bbox("all")))
        self.admin_team_canvas.bind("<Configure>", self._handle_admin_team_canvas_resize)
        self._register_mousewheel_route(self.admin_team_cards_frame, self.admin_team_canvas)

        self._build_admin_team_editor_cards()
        self._refresh_admin_team_editor_from_state()

    def _build_admin_portal_tab(self) -> None:
        self.admin_portal_tab.columnconfigure(0, weight=1)
        self.admin_portal_tab.rowconfigure(1, weight=1)

        header = tk.Frame(self.admin_portal_tab, bg="#0b0b0c")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(1, weight=1)

        tk.Label(header, text="SINCRONIZACAO COM O PORTAL", bg="#0b0b0c", fg="#f3f3f3", font=(self.button_font_family, 24)).grid(row=0, column=0, sticky="w")
        self.portal_admin_status_var = tk.StringVar(value="Conecte o backend do portal para aprovar e importar times.")
        tk.Label(header, textvariable=self.portal_admin_status_var, bg="#0b0b0c", fg="#a2a8b0", font=(self.title_font_family, 10), anchor="e").grid(row=0, column=1, sticky="ew", padx=(18, 0))

        actions = tk.Frame(self.admin_portal_tab, bg="#0b0b0c")
        actions.grid(row=1, column=0, sticky="nsew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.rowconfigure(1, weight=1)

        top_actions = tk.Frame(actions, bg="#0b0b0c")
        top_actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Button(top_actions, text="Atualizar fila", command=self._refresh_portal_admin_dashboard).pack(side="left")
        ttk.Button(top_actions, text="Importar times aprovados", command=self._import_approved_teams_from_portal).pack(side="left", padx=(10, 0))
        self.portal_registrations_button = ttk.Button(top_actions, text="Fechar inscrições", command=self._toggle_portal_registrations)
        self.portal_registrations_button.pack(side="left", padx=(10, 0))

        list_card = tk.Frame(actions, bg="#111214", highlightthickness=1, highlightbackground="#1f2125", padx=16, pady=16)
        list_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)

        tk.Label(list_card, text="SUBMISSOES PENDENTES", bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 20)).grid(row=0, column=0, sticky="w")
        self.portal_pending_listbox = tk.Listbox(list_card, activestyle="none", borderwidth=0, highlightthickness=0, bg="#0d0f12", fg="#f1f3f5", selectbackground="#eef0f2", selectforeground="#050607")
        self.portal_pending_listbox.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        self.portal_pending_listbox.bind("<<ListboxSelect>>", self._load_selected_portal_submission)

        detail_card = tk.Frame(actions, bg="#111214", highlightthickness=1, highlightbackground="#1f2125", padx=16, pady=16)
        detail_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        detail_card.columnconfigure(0, weight=1)
        detail_card.rowconfigure(1, weight=1)

        tk.Label(detail_card, text="DETALHES DA ANALISE", bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 20)).grid(row=0, column=0, sticky="w")
        self.portal_submission_summary_var = tk.StringVar(value="Selecione uma submissao para revisar os dados enviados.")
        tk.Label(detail_card, textvariable=self.portal_submission_summary_var, justify="left", wraplength=460, bg="#111214", fg="#c6ccd3", anchor="nw", font=(self.title_font_family, 10)).grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        detail_actions = tk.Frame(detail_card, bg="#111214")
        detail_actions.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        ttk.Button(detail_actions, text="Aprovar", style="Primary.TButton", command=self._approve_selected_portal_submission).pack(side="left")
        ttk.Button(detail_actions, text="Recusar", command=self._reject_selected_portal_submission).pack(side="left", padx=(10, 0))
        ttk.Button(detail_actions, text="Ver time", command=self._open_selected_portal_submission_view).pack(side="left", padx=(10, 0))

    def _build_admin_users_tab(self) -> None:
        self.admin_users_tab.columnconfigure(0, weight=1)
        self.admin_users_tab.rowconfigure(1, weight=1)

        header = tk.Frame(self.admin_users_tab, bg="#0b0b0c")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(1, weight=1)

        tk.Label(header, text="USUARIOS DO PORTAL", bg="#0b0b0c", fg="#f3f3f3", font=(self.button_font_family, 24)).grid(row=0, column=0, sticky="w")
        self.portal_users_status_var = tk.StringVar(value="Carregue os usuarios que ja entraram no site.")
        tk.Label(header, textvariable=self.portal_users_status_var, bg="#0b0b0c", fg="#a2a8b0", font=(self.title_font_family, 10), anchor="e").grid(row=0, column=1, sticky="ew", padx=(18, 0))

        shell = tk.Frame(self.admin_users_tab, bg="#0b0b0c")
        shell.grid(row=1, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(1, weight=1)

        top_actions = tk.Frame(shell, bg="#0b0b0c")
        top_actions.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Button(top_actions, text="Atualizar usuarios", command=self._refresh_portal_users).pack(side="left")

        list_card = tk.Frame(shell, bg="#111214", highlightthickness=1, highlightbackground="#1f2125", padx=16, pady=16)
        list_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        list_card.columnconfigure(0, weight=1)
        list_card.rowconfigure(1, weight=1)
        tk.Label(list_card, text="USUARIOS CADASTRADOS", bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 20)).grid(row=0, column=0, sticky="w")
        self.portal_users_listbox = tk.Listbox(list_card, activestyle="none", borderwidth=0, highlightthickness=0, bg="#0d0f12", fg="#f1f3f5", selectbackground="#eef0f2", selectforeground="#050607")
        self.portal_users_listbox.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        self.portal_users_listbox.bind("<<ListboxSelect>>", self._load_selected_portal_user)

        detail_card = tk.Frame(shell, bg="#111214", highlightthickness=1, highlightbackground="#1f2125", padx=16, pady=16)
        detail_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
        detail_card.columnconfigure(0, weight=1)
        detail_card.rowconfigure(1, weight=1)
        tk.Label(detail_card, text="DETALHES DO USUARIO", bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 20)).grid(row=0, column=0, sticky="w")
        self.portal_user_summary_var = tk.StringVar(value="Selecione um usuario para ver os detalhes.")
        tk.Label(detail_card, textvariable=self.portal_user_summary_var, justify="left", wraplength=460, bg="#111214", fg="#c6ccd3", anchor="nw", font=(self.title_font_family, 10)).grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        riot_form = tk.Frame(detail_card, bg="#111214")
        riot_form.grid(row=2, column=0, sticky="ew", pady=(16, 0))
        riot_form.columnconfigure(1, weight=1)
        tk.Label(riot_form, text="Riot ID", bg="#111214", fg="#c6ccd3", font=(self.title_font_family, 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.portal_user_riot_id_var = tk.StringVar(value="")
        ttk.Entry(riot_form, textvariable=self.portal_user_riot_id_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(riot_form, text="Salvar Riot ID", command=self._save_selected_portal_user_riot_id).grid(row=0, column=2, sticky="e", padx=(10, 0))

    def _build_admin_bracket_tab(self) -> None:
        self.admin_bracket_tab.columnconfigure(0, weight=1)
        self.admin_bracket_tab.rowconfigure(2, weight=1)

        summary = ttk.LabelFrame(self.admin_bracket_tab, text="Montagem da chave", padding=16)
        summary.grid(row=0, column=0, sticky="ew")
        summary.columnconfigure(0, weight=1)

        ttk.Label(summary, text="A ordem abaixo define a entrada dos times na bracket.", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.admin_bracket_teams_text = tk.Text(summary, height=8, wrap="word", relief="flat", padx=12, pady=12)
        self.admin_bracket_teams_text.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        action_row = ttk.Frame(summary)
        action_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        action_row.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(action_row, text="Preencher com times do painel", command=self._populate_admin_bracket_from_profiles).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(action_row, text="Salvar lista", command=self._save_bracket_teams).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(action_row, text="Montar chave", style="Primary.TButton", command=self._build_bracket).grid(row=0, column=2, sticky="ew", padx=(8, 0))

        schedule_card = ttk.LabelFrame(self.admin_bracket_tab, text="Datas dos confrontos", padding=16)
        schedule_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        schedule_card.columnconfigure(0, weight=1)
        ttk.Label(schedule_card, text="Use o formato ID = data. Exemplo: UB1 = 22/03", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        self.match_schedule_text = tk.Text(schedule_card, height=7, wrap="word", relief="flat", padx=12, pady=12)
        self.match_schedule_text.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        schedule_actions = ttk.Frame(schedule_card)
        schedule_actions.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        schedule_actions.columnconfigure((0, 1), weight=1)
        ttk.Button(schedule_actions, text="Preencher IDs da chave", command=self._populate_match_schedule_editor).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(schedule_actions, text="Salvar datas", style="Primary.TButton", command=self._save_match_schedule).grid(row=0, column=1, sticky="ew", padx=(8, 0))

        tips = ttk.LabelFrame(self.admin_bracket_tab, text="Observacoes", padding=16)
        tips.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        ttk.Label(
            tips,
            text="A pagina Chave agora mostra apenas a bracket. Toda alteracao de lista, datas e montagem passa pelo Painel.",
            justify="left",
        ).grid(row=0, column=0, sticky="nw")

    def _build_admin_matches_tab(self) -> None:
        _shell, _canvas, content = self._create_scrollable_container(self.admin_matches_tab, bg="#f4f6f8", show_scrollbar=True)
        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, weight=1)

        match_list_frame = tk.Frame(content, bg="#111214", highlightthickness=1, highlightbackground="#23262b", padx=16, pady=16)
        match_list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        match_list_frame.columnconfigure(0, weight=1)
        match_list_frame.rowconfigure(3, weight=1)

        tk.Label(match_list_frame, text="CENTRAL DE PARTIDAS", bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 24)).grid(row=0, column=0, sticky="w")
        tk.Label(match_list_frame, text="Selecione uma serie, revise os dados e puxe automaticamente a ultima partida dos capitaes.", bg="#111214", fg="#9ca3ad", font=(self.title_font_family, 10, "bold")).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.match_selection_var = tk.StringVar()
        self.match_combo = ttk.Combobox(match_list_frame, state="readonly", textvariable=self.match_selection_var)
        self.match_combo.grid(row=2, column=0, sticky="ew", pady=(12, 12))
        self.match_combo.bind("<<ComboboxSelected>>", self._load_selected_match)

        self.match_listbox = tk.Listbox(match_list_frame, activestyle="none", borderwidth=0, highlightthickness=0, bg="#0d0f12", fg="#f1f3f5", selectbackground="#eef0f2", selectforeground="#050607")
        self.match_listbox.grid(row=3, column=0, sticky="nsew")
        self.match_listbox.bind("<<ListboxSelect>>", self._load_selected_match_from_listbox)

        details_frame = tk.Frame(content, bg="#111214", highlightthickness=1, highlightbackground="#23262b", padx=18, pady=18)
        details_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(4, weight=1)

        header = tk.Frame(details_frame, bg="#111214")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        self.selected_match_title = tk.Label(header, text="Nenhuma partida selecionada.", bg="#111214", fg="#f3f3f3", anchor="w", font=(self.button_font_family, 22))
        self.selected_match_title.grid(row=0, column=0, sticky="w")
        self.match_status_badge = tk.Label(header, text="AGUARDANDO", bg="#262a30", fg="#f1f3f5", padx=12, pady=6, font=(self.title_font_family, 9, "bold"))
        self.match_status_badge.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.official_lookup_status_var = tk.StringVar(value="Validacao oficial pronta para buscar a ultima partida dos capitaes.")
        tk.Label(header, textvariable=self.official_lookup_status_var, bg="#111214", fg="#96a0ac", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        api_row = tk.Frame(details_frame, bg="#111214")
        api_row.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        api_row.columnconfigure(1, weight=1)
        tk.Label(api_row, text="API HenrikDev", bg="#111214", fg="#b4bcc6", font=(self.title_font_family, 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.henrik_api_key_var = tk.StringVar(value=self._get_henrik_api_key_value())
        self.henrik_api_key_entry = tk.Entry(api_row, textvariable=self.henrik_api_key_var, relief="flat", bg="#14181d", fg="#f3f3f3", insertbackground="#f3f3f3", show="*")
        self.henrik_api_key_entry.grid(row=0, column=1, sticky="ew")
        tk.Button(api_row, text="Salvar chave(s)", command=self._save_henrik_api_key_from_form, relief="flat", borderwidth=0, bg="#efefef", fg="#050607", activebackground="#ffffff", activeforeground="#050607", cursor="hand2", font=(self.button_font_family, 14), padx=18, pady=8).grid(row=0, column=2, padx=(12, 0))
        tk.Label(api_row, text="Aceita varias chaves separadas por virgula, ponto e virgula ou quebra de linha.", bg="#111214", fg="#7f8995", anchor="w", font=(self.title_font_family, 9, "bold")).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(8, 0))

        summary = tk.Frame(details_frame, bg="#0d0f12", highlightthickness=1, highlightbackground="#20242a", padx=14, pady=14)
        summary.grid(row=2, column=0, sticky="ew", pady=(14, 14))
        summary.columnconfigure((0, 1), weight=1)

        team_one_card = tk.Frame(summary, bg="#14181d", padx=12, pady=12)
        team_one_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(team_one_card, text="TIME 1", bg="#14181d", fg="#9ca6b2", anchor="w", font=(self.title_font_family, 9, "bold")).pack(fill="x")
        self.match_team1_var = tk.StringVar(value="-")
        tk.Label(team_one_card, textvariable=self.match_team1_var, bg="#14181d", fg="#f3f3f3", anchor="w", font=(self.button_font_family, 18)).pack(fill="x", pady=(6, 0))
        self.match_team1_captain_var = tk.StringVar(value="Capitao: -")
        tk.Label(team_one_card, textvariable=self.match_team1_captain_var, bg="#14181d", fg="#b7c0cb", anchor="w", font=(self.title_font_family, 10, "bold")).pack(fill="x", pady=(8, 0))

        team_two_card = tk.Frame(summary, bg="#14181d", padx=12, pady=12)
        team_two_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        tk.Label(team_two_card, text="TIME 2", bg="#14181d", fg="#9ca6b2", anchor="w", font=(self.title_font_family, 9, "bold")).pack(fill="x")
        self.match_team2_var = tk.StringVar(value="-")
        tk.Label(team_two_card, textvariable=self.match_team2_var, bg="#14181d", fg="#f3f3f3", anchor="w", font=(self.button_font_family, 18)).pack(fill="x", pady=(6, 0))
        self.match_team2_captain_var = tk.StringVar(value="Capitao: -")
        tk.Label(team_two_card, textvariable=self.match_team2_captain_var, bg="#14181d", fg="#b7c0cb", anchor="w", font=(self.title_font_family, 10, "bold")).pack(fill="x", pady=(8, 0))

        form_grid = tk.Frame(details_frame, bg="#111214")
        form_grid.grid(row=3, column=0, sticky="ew")
        form_grid.columnconfigure((0, 1), weight=1)

        result_card = tk.Frame(form_grid, bg="#0d0f12", highlightthickness=1, highlightbackground="#20242a", padx=14, pady=14)
        result_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        result_card.columnconfigure(1, weight=1)
        tk.Label(result_card, text="RESULTADO", bg="#0d0f12", fg="#f1f3f5", anchor="w", font=(self.button_font_family, 18)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.series_guidance_var = tk.StringVar(value="Serie pronta para preenchimento guiado.")
        tk.Label(result_card, textvariable=self.series_guidance_var, bg="#0d0f12", fg="#96a0ac", anchor="w", justify="left", font=(self.title_font_family, 10, "bold")).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        tk.Label(result_card, text="Vencedor", bg="#0d0f12", fg="#b4bcc6", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=2, column=0, sticky="w", pady=4)
        self.match_winner_var = tk.StringVar()
        self.match_winner_combo = ttk.Combobox(result_card, state="readonly", textvariable=self.match_winner_var)
        self.match_winner_combo.grid(row=2, column=1, sticky="ew", pady=4)

        tk.Label(result_card, text="Placar", bg="#0d0f12", fg="#b4bcc6", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=3, column=0, sticky="w", pady=4)
        score_frame = tk.Frame(result_card, bg="#0d0f12")
        score_frame.grid(row=3, column=1, sticky="ew", pady=4)
        self.team1_score_var = tk.StringVar()
        self.team2_score_var = tk.StringVar()
        ttk.Entry(score_frame, textvariable=self.team1_score_var, width=8).grid(row=0, column=0, padx=(0, 8))
        ttk.Label(score_frame, text="x").grid(row=0, column=1)
        ttk.Entry(score_frame, textvariable=self.team2_score_var, width=8).grid(row=0, column=2, padx=(8, 0))

        tk.Label(result_card, text="Mapa", bg="#0d0f12", fg="#b4bcc6", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=4, column=0, sticky="w", pady=4)
        self.map_name_var = tk.StringVar()
        ttk.Entry(result_card, textvariable=self.map_name_var).grid(row=4, column=1, sticky="ew", pady=4)

        self.official_suggestion_var = tk.StringVar(value="Sem sugestao oficial carregada.")
        tk.Label(result_card, textvariable=self.official_suggestion_var, bg="#0d0f12", fg="#d8dde3", anchor="w", justify="left", font=(self.title_font_family, 10)).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        tk.Button(result_card, text="Aplicar sugestao oficial", command=self._apply_official_suggestion_to_form, relief="flat", borderwidth=0, bg="#1f2329", fg="#f3f3f3", activebackground="#2a2f36", activeforeground="#ffffff", cursor="hand2", font=(self.button_font_family, 14), padx=18, pady=8).grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 0))

        official_card = tk.Frame(form_grid, bg="#0d0f12", highlightthickness=1, highlightbackground="#20242a", padx=14, pady=14)
        official_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        official_card.columnconfigure(1, weight=1)
        tk.Label(official_card, text="DADOS OFICIAIS", bg="#0d0f12", fg="#f1f3f5", anchor="w", font=(self.button_font_family, 18)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        tk.Label(official_card, text="ACS", bg="#0d0f12", fg="#b4bcc6", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=1, column=0, sticky="w", pady=4)
        self.official_acs_var = tk.StringVar()
        ttk.Entry(official_card, textvariable=self.official_acs_var).grid(row=1, column=1, sticky="ew", pady=4)

        tk.Label(official_card, text="K/D", bg="#0d0f12", fg="#b4bcc6", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=2, column=0, sticky="w", pady=4)
        self.official_kd_var = tk.StringVar()
        ttk.Entry(official_card, textvariable=self.official_kd_var).grid(row=2, column=1, sticky="ew", pady=4)

        tk.Label(official_card, text="MVP", bg="#0d0f12", fg="#b4bcc6", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=3, column=0, sticky="w", pady=4)
        self.official_mvp_var = tk.StringVar()
        ttk.Entry(official_card, textvariable=self.official_mvp_var).grid(row=3, column=1, sticky="ew", pady=4)

        tk.Label(official_card, text="Resumo", bg="#0d0f12", fg="#b4bcc6", anchor="w", font=(self.title_font_family, 10, "bold")).grid(row=4, column=0, sticky="w", pady=4)
        self.official_result_var = tk.StringVar()
        ttk.Entry(official_card, textvariable=self.official_result_var).grid(row=4, column=1, sticky="ew", pady=4)

        notes_card = tk.Frame(details_frame, bg="#0d0f12", highlightthickness=1, highlightbackground="#20242a", padx=14, pady=14)
        notes_card.grid(row=4, column=0, sticky="nsew", pady=(14, 0))
        notes_card.columnconfigure(0, weight=1)
        notes_card.rowconfigure(1, weight=1)
        tk.Label(notes_card, text="OBSERVACOES E AJUSTES MANUAIS", bg="#0d0f12", fg="#f1f3f5", anchor="w", font=(self.button_font_family, 18)).grid(row=0, column=0, sticky="w")
        self.notes_text = tk.Text(notes_card, height=8, wrap="word", relief="flat", bg="#14181d", fg="#f3f3f3", insertbackground="#f3f3f3", padx=12, pady=12)
        self.notes_text.grid(row=1, column=0, sticky="nsew", pady=(12, 0))

        match_actions = ttk.Frame(details_frame)
        match_actions.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        match_actions.columnconfigure((0, 1, 2), weight=1)

        ttk.Button(match_actions, text="Salvar resultado", style="Primary.TButton", command=self._save_selected_match_result).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )
        ttk.Button(match_actions, text="Limpar resultado", command=self._clear_selected_match_result).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        self.validate_official_button = ttk.Button(match_actions, text="Buscar ultima dos capitaes", command=self._validate_official_data)
        self.validate_official_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))

    def _build_bracket_tab(self) -> None:
        self.bracket_tab.columnconfigure(0, weight=1)
        self.bracket_tab.rowconfigure(0, weight=1)

        board_shell = tk.Frame(self.bracket_tab, bg="#0b0b0c")
        board_shell.grid(row=0, column=0, sticky="nsew")
        board_shell.columnconfigure(0, weight=1)
        board_shell.rowconfigure(0, weight=1)

        board_frame = tk.Frame(board_shell, bg="#111214", highlightthickness=1, highlightbackground="#1e2023")
        board_frame.grid(row=0, column=0, sticky="nsew")
        board_frame.columnconfigure(0, weight=1)
        board_frame.rowconfigure(0, weight=1)

        self.bracket_canvas = tk.Canvas(
            board_frame,
            bg="#111214",
            highlightthickness=0,
            bd=0,
        )
        self.bracket_canvas.grid(row=0, column=0, sticky="nsew")
        self.bracket_canvas.bind("<Configure>", lambda _event: self._refresh_bracket_view())
        self._register_mousewheel_route(board_shell, self.bracket_canvas)
        self._register_mousewheel_route(board_frame, self.bracket_canvas)
        self._register_mousewheel_route(self.bracket_canvas, self.bracket_canvas)

    def _build_matches_tab(self) -> None:
        self.matches_tab.columnconfigure(0, weight=1)
        self.matches_tab.rowconfigure(0, weight=1)
        self.public_matches_status_var = tk.StringVar(value="Nenhuma partida pronta para exibir.")

        shell = tk.Frame(self.matches_tab, bg="#0b0b0c")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        board = tk.Frame(shell, bg="#111214", highlightthickness=1, highlightbackground="#232427")
        board.grid(row=0, column=0, sticky="nsew")
        board.columnconfigure(0, weight=1)
        board.rowconfigure(0, weight=1)

        self.matches_canvas = tk.Canvas(board, bg="#111214", highlightthickness=0, bd=0)
        self.matches_canvas.grid(row=0, column=0, sticky="nsew")
        matches_scrollbar = ttk.Scrollbar(board, orient="vertical", command=self.matches_canvas.yview)
        matches_scrollbar.grid(row=0, column=1, sticky="ns")
        self.matches_canvas.configure(yscrollcommand=matches_scrollbar.set)
        self._register_mousewheel_route(shell, self.matches_canvas)
        self._register_mousewheel_route(board, self.matches_canvas)
        self._register_mousewheel_route(self.matches_canvas, self.matches_canvas)

        self.matches_cards_frame = tk.Frame(self.matches_canvas, bg="#111214", padx=18, pady=18)
        self.matches_canvas_window = self.matches_canvas.create_window((0, 0), window=self.matches_cards_frame, anchor="nw")
        self.matches_cards_frame.bind(
            "<Configure>",
            lambda _event: self.matches_canvas.configure(scrollregion=self.matches_canvas.bbox("all")),
        )
        self.matches_canvas.bind("<Configure>", self._schedule_public_matches_refresh)
        self._register_mousewheel_route(self.matches_cards_frame, self.matches_canvas)

    def _schedule_public_matches_refresh(self, _event=None) -> None:
        if not hasattr(self, "matches_canvas"):
            return
        canvas_width = max(self.matches_canvas.winfo_width(), 1)
        self.matches_canvas.itemconfigure(self.matches_canvas_window, width=canvas_width)
        if self.public_match_resize_job:
            self.after_cancel(self.public_match_resize_job)
        self.public_match_resize_job = self.after(60, self._refresh_public_matches_view)

    def _refresh_public_matches_view(self) -> None:
        if not hasattr(self, "matches_cards_frame"):
            return

        self.public_match_resize_job = None
        self.public_match_logo_refs = []
        for child in self.matches_cards_frame.winfo_children():
            child.destroy()

        defined_matches = [match for match in self.resolved_matches if match_can_receive_result(match)]
        completed_matches = [match for match in defined_matches if self._match_is_completed(match)]
        pending_matches = [match for match in defined_matches if not self._match_is_completed(match)]
        ordered_matches = pending_matches + completed_matches

        if not defined_matches:
            self.public_matches_status_var.set("Nenhuma partida com dois times definidos ainda.")
            tk.Label(self.matches_cards_frame, text="PARTIDAS", bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 30)).pack(anchor="center", pady=(10, 22))
            empty_card = tk.Frame(self.matches_cards_frame, bg="#16171a", highlightthickness=1, highlightbackground="#292c31", padx=26, pady=26)
            empty_card.pack(fill="both", expand=True)
            tk.Label(empty_card, text="PARTIDAS AINDA NAO DEFINIDAS", bg="#16171a", fg="#f3f3f3", font=(self.button_font_family, 25)).pack(anchor="w")
            tk.Label(
                empty_card,
                text="Monte a chave no Painel e cadastre os resultados para esta tela mostrar os proximos confrontos e o historico concluido.",
                bg="#16171a",
                fg="#a2a8b0",
                justify="left",
                font=(self.title_font_family, 11),
            ).pack(anchor="w", pady=(10, 0))
            return

        self.public_matches_status_var.set(f"{len(defined_matches)} partidas exibidas")
        available_width = max(self.matches_canvas.winfo_width(), 900)
        columns = 1 if available_width < 900 else 2 if available_width < 1280 else 3

        tk.Label(self.matches_cards_frame, text="PARTIDAS", bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 30)).pack(anchor="center", pady=(10, 22))
        grid = tk.Frame(self.matches_cards_frame, bg="#111214")
        grid.pack(fill="x")
        for column_index in range(columns):
            grid.columnconfigure(column_index, weight=1)

        for index, match in enumerate(ordered_matches):
            row_index = index // columns
            column_index = index % columns
            self._build_public_match_card(grid, match, row_index, column_index)

    def _build_public_matches_section(self, parent: tk.Widget, title: str, subtitle: str, matches: list[dict], columns: int, empty_text: str) -> None:
        section = tk.Frame(parent, bg="#111214")
        section.pack(fill="x", pady=(0, 18))
        tk.Label(section, text=title, bg="#111214", fg="#f3f3f3", font=(self.button_font_family, 24)).pack(anchor="w")

        grid = tk.Frame(section, bg="#111214")
        grid.pack(fill="x", pady=(10, 0))
        for column_index in range(columns):
            grid.columnconfigure(column_index, weight=1)

        if not matches:
            empty_state = tk.Frame(grid, bg="#17181c", highlightthickness=1, highlightbackground="#2a2d32", padx=18, pady=18)
            empty_state.grid(row=0, column=0, columnspan=columns, sticky="ew")
            tk.Label(empty_state, text=empty_text, bg="#17181c", fg="#a4acb6", font=(self.title_font_family, 11)).pack(anchor="w")
            return

        for index, match in enumerate(matches):
            row_index = index // columns
            column_index = index % columns
            self._build_public_match_card(grid, match, row_index, column_index)

    def _build_public_match_card(self, parent: tk.Widget, match: dict, row_index: int, column_index: int) -> None:
        is_completed = self._match_is_completed(match)
        card = tk.Frame(
            parent,
            bg="#17181c",
            highlightthickness=1,
            highlightbackground="#e8ecef" if is_completed else "#2d3138",
            padx=18,
            pady=18,
        )
        card.grid(row=row_index, column=column_index, sticky="nsew", padx=8, pady=8)
        parent.grid_rowconfigure(row_index, weight=1)

        top_row = tk.Frame(card, bg="#17181c")
        top_row.pack(fill="x")
        tk.Label(top_row, text=match["id"], bg="#24262b", fg="#f3f3f3", font=(self.button_font_family, 15), padx=10, pady=4).pack(side="left")
        tk.Label(top_row, text=match.get("scheduled_date", "").strip() or "Sem data", bg="#17181c", fg="#a2a8b0", font=(self.title_font_family, 10, "bold")).pack(side="right")

        tk.Label(card, text=f"{match['team1']} x {match['team2']}", bg="#17181c", fg="#f3f3f3", anchor="w", font=(self.title_font_family, 11, "bold")).pack(fill="x", pady=(12, 2))
        tk.Label(card, text=f"{match['stage']} | {match['best_of']} | {self._get_match_series_count_label(match)}", bg="#17181c", fg="#7d8590", anchor="w", font=(self.title_font_family, 9)).pack(fill="x")

        duel = tk.Frame(card, bg="#17181c")
        duel.pack(fill="x", pady=(16, 12))
        duel.columnconfigure((0, 2), weight=1)
        self._build_public_match_team_block(duel, match["team1"], 0)

        center_score = tk.Frame(duel, bg="#17181c")
        center_score.grid(row=0, column=1, padx=14)
        if is_completed:
            score_text = f"{match.get('team1_score', '-') or '-'}  X  {match.get('team2_score', '-') or '-'}"
            center_color = "#f1f3f4"
            subtitle = match.get("winner", "").strip() or "Resultado salvo"
        else:
            score_text = "VS"
            center_color = "#9ba3ad"
            subtitle = "Aguardando resultado"
        tk.Label(center_score, text=score_text, bg="#17181c", fg=center_color, font=(self.button_font_family, 28)).pack()
        tk.Label(center_score, text=subtitle, bg="#17181c", fg="#7d8590", font=(self.title_font_family, 9)).pack(pady=(4, 0))

        self._build_public_match_team_block(duel, match["team2"], 2)

        footer = tk.Frame(card, bg="#17181c")
        footer.pack(fill="x")
        summary_text = self._get_match_summary_text(match)
        tk.Label(footer, text=summary_text, bg="#17181c", fg="#cdd2d9", justify="left", anchor="w", font=(self.title_font_family, 10)).pack(side="left", fill="x", expand=True)
        if is_completed:
            tk.Button(
                footer,
                text="DETALHES",
                command=lambda match_id=match["id"]: self._open_public_match_details(match_id),
                relief="flat",
                borderwidth=0,
                bg="#f3f3f3",
                fg="#050607",
                activebackground="#ffffff",
                activeforeground="#000000",
                cursor="hand2",
                font=(self.button_font_family, 15),
                padx=14,
                pady=8,
            ).pack(side="right", padx=(12, 0))

    def _build_public_match_team_block(self, parent: tk.Widget, team_name: str, column_index: int) -> None:
        block = tk.Frame(parent, bg="#17181c")
        block.grid(row=0, column=column_index, sticky="nsew")
        logo_image = self._load_public_match_logo(team_name, max_size=74)
        if logo_image:
            tk.Label(block, image=logo_image, bg="#17181c").pack(pady=(0, 8))
        else:
            tk.Label(block, text=team_name[:1].upper() if team_name and team_name != "A definir" else "?", bg="#22252a", fg="#f3f3f3", width=4, height=2, font=(self.button_font_family, 18)).pack(pady=(0, 8))
        tk.Label(block, text=team_name, bg="#17181c", fg="#f3f3f3", justify="center", font=(self.title_font_family, 11, "bold"), wraplength=180).pack()

    def _load_public_match_logo(self, team_name: str, max_size: int = 74) -> tk.PhotoImage | None:
        profile = self._get_team_profile_by_name(team_name)
        if not profile:
            return None
        logo_image = self._load_logo_image(profile.get("logo_path", ""), max_size=max_size)
        if logo_image:
            self.public_match_logo_refs.append(logo_image)
        return logo_image

    def _match_is_completed(self, match: dict) -> bool:
        if match.get("winner", "").strip():
            return True
        if str(match.get("team1_score", "")).strip() and str(match.get("team2_score", "")).strip():
            return True
        return bool(match.get("official_result", "").strip())

    def _get_match_summary_text(self, match: dict) -> str:
        if self._match_is_completed(match):
            map_entries = self._get_match_map_entries(match)
            map_names = [entry.get("map_name", "").strip() for entry in map_entries if entry.get("map_name", "").strip()]
            mvp_name = match.get("official_mvp", "").strip() or self._get_official_meta(match, "mvp") or "MVP pendente"
            if map_names:
                return f"Mapas: {', '.join(map_names[:3])}\nMVP: {mvp_name}"
            return f"{self._get_match_series_count_label(match)}\nMVP: {mvp_name}"
        return f"Bracket: {match['bracket']}\nSerie: {match['best_of']}"

    def _get_match_map_entries(self, match: dict) -> list[dict]:
        official_data = match.get("official_data", {})
        if isinstance(official_data, dict):
            maps_payload = official_data.get("maps", [])
            if isinstance(maps_payload, list):
                normalized_maps = [payload for payload in maps_payload if isinstance(payload, dict)]
                if normalized_maps:
                    return normalized_maps

        fallback_map_name = match.get("map_name", "").strip() or self._get_official_meta(match, "map_name")
        fallback_result = match.get("official_result", "").strip()
        if fallback_map_name or fallback_result or self._match_is_completed(match):
            return [
                {
                    "map_name": fallback_map_name,
                    "result_line": fallback_result,
                    "winner": match.get("winner", "").strip(),
                    "started_at": self._get_official_meta(match, "started_at") or match.get("scheduled_date", "").strip(),
                    "mvp": match.get("official_mvp", "").strip() or self._get_official_meta(match, "mvp"),
                    "teams": [
                        {"name": match["team1"], "score": match.get("team1_score", ""), "players": []},
                        {"name": match["team2"], "score": match.get("team2_score", ""), "players": []},
                    ],
                }
            ]
        return []

    def _get_match_series_count_label(self, match: dict) -> str:
        map_entries = self._get_match_map_entries(match)
        map_count = len(map_entries)
        return f"{map_count} mapa{'s' if map_count != 1 else ''}"

    def _get_official_meta(self, match: dict, key: str) -> str:
        official_data = match.get("official_data", {})
        if not isinstance(official_data, dict):
            return ""
        metadata = official_data.get("metadata", {})
        if not isinstance(metadata, dict):
            return ""
        value = metadata.get(key, "")
        return str(value).strip()

    def _open_public_match_details(self, match_id: str) -> None:
        match = self._get_match_by_id(match_id)
        if not match:
            return

        details_window = tk.Toplevel(self)
        details_window.title(f"Serie {match['id']}")
        details_window.transient(self)
        details_window.configure(bg="#0b0b0c")
        details_window.geometry("1120x760")
        details_window.minsize(980, 700)
        details_window.match_details_fullscreen = False
        details_window.bind("<F11>", lambda _event, window=details_window: self._toggle_match_details_fullscreen(window))
        details_window.bind("<Escape>", lambda _event, window=details_window: self._exit_match_details_fullscreen(window))

        container = tk.Frame(details_window, bg="#0b0b0c", padx=22, pady=22)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)

        title_block = tk.Frame(container, bg="#0b0b0c")
        title_block.grid(row=0, column=0, sticky="ew")
        tk.Label(title_block, text="PARTIDAS", bg="#0b0b0c", fg="#f3f3f3", font=(self.button_font_family, 26)).pack(anchor="center")
        tk.Label(title_block, text=f"{match['team1']} x {match['team2']}", bg="#0b0b0c", fg="#f3f3f3", font=(self.title_font_family, 15, "bold")).pack(anchor="center", pady=(10, 0))
        tk.Label(title_block, text=f"{match['best_of']} | {match.get('scheduled_date', '').strip() or 'Sem data'} | {self._get_match_series_count_label(match)}", bg="#0b0b0c", fg="#98a0ab", font=(self.title_font_family, 10)).pack(anchor="center", pady=(6, 0))

        map_entries = self._get_match_map_entries(match)
        maps_card = tk.Frame(container, bg="#15171b", highlightthickness=1, highlightbackground="#2a2d32", padx=18, pady=18)
        maps_card.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        maps_card.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)
        tk.Label(maps_card, text="MAPAS / PARTIDAS JOGADAS", bg="#15171b", fg="#f3f3f3", font=(self.button_font_family, 22)).grid(row=0, column=0, sticky="w")
        maps_grid = tk.Frame(maps_card, bg="#15171b")
        maps_grid.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        maps_grid.columnconfigure((0, 1), weight=1)
        maps_card.rowconfigure(1, weight=1)

        if map_entries:
            for index, map_entry in enumerate(map_entries):
                self._build_public_match_map_card(maps_grid, match, map_entry, index)
        else:
            empty_state = tk.Frame(maps_grid, bg="#17181c", highlightthickness=1, highlightbackground="#2a2d32", padx=18, pady=18)
            empty_state.grid(row=0, column=0, sticky="ew")
            tk.Label(empty_state, text="Nenhum mapa detalhado foi encontrado para esta serie.", bg="#17181c", fg="#cdd2d9", font=(self.title_font_family, 11)).pack(anchor="w")

        notes = match.get("notes", "").strip()
        if notes:
            notes_card = tk.Frame(container, bg="#15171b", highlightthickness=1, highlightbackground="#2a2d32", padx=18, pady=18)
            notes_card.grid(row=2, column=0, sticky="ew", pady=(14, 0))
            tk.Label(notes_card, text="OBSERVACOES", bg="#15171b", fg="#f3f3f3", font=(self.button_font_family, 20)).pack(anchor="w")
            tk.Label(notes_card, text=notes, justify="left", bg="#15171b", fg="#c8cdd3", wraplength=980, font=(self.title_font_family, 10)).pack(anchor="w", pady=(10, 0))

    def _build_public_match_map_card(self, parent: tk.Widget, match: dict, map_entry: dict, index: int) -> None:
        card = tk.Frame(parent, bg="#17181c", highlightthickness=1, highlightbackground="#2a2d32", padx=14, pady=14)
        card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
        result_line = str(map_entry.get("result_line", "")).strip()
        started_at = str(map_entry.get("started_at", "")).strip() or "-"
        winner_name = str(map_entry.get("winner", "")).strip() or "-"
        mvp_name = str(map_entry.get("mvp", "")).strip() or "-"
        tk.Label(card, text=f"PARTIDA {index + 1}", bg="#24262b", fg="#f3f3f3", font=(self.button_font_family, 14), padx=10, pady=4).pack(anchor="w")
        tk.Label(card, text=str(map_entry.get("map_name", "")).strip() or "Mapa nao informado", bg="#17181c", fg="#f3f3f3", anchor="w", font=(self.title_font_family, 11, "bold")).pack(fill="x", pady=(12, 2))
        tk.Label(card, text=result_line or "Resultado nao informado", bg="#17181c", fg="#cdd2d9", anchor="w", justify="left", font=(self.title_font_family, 10)).pack(fill="x")
        tk.Label(card, text=f"Vencedor: {winner_name}", bg="#17181c", fg="#9aa2ac", anchor="w", font=(self.title_font_family, 9)).pack(fill="x", pady=(10, 0))
        tk.Label(card, text=f"MVP: {mvp_name}", bg="#17181c", fg="#9aa2ac", anchor="w", font=(self.title_font_family, 9)).pack(fill="x", pady=(4, 0))
        actions = tk.Frame(card, bg="#17181c")
        actions.pack(fill="x", pady=(12, 0))
        tk.Label(actions, text=f"Data: {started_at}", bg="#17181c", fg="#9aa2ac", anchor="w", font=(self.title_font_family, 9)).pack(side="left")
        tk.Button(
            actions,
            text="DETALHES",
            command=lambda entry=dict(map_entry), current_match=dict(match), map_index=index: self._open_public_map_details(current_match, entry, map_index),
            relief="flat",
            borderwidth=0,
            bg="#f3f3f3",
            fg="#050607",
            activebackground="#ffffff",
            activeforeground="#000000",
            cursor="hand2",
            font=(self.button_font_family, 14),
            padx=12,
            pady=6,
        ).pack(side="right")

    def _open_public_map_details(self, match: dict, map_entry: dict, map_index: int) -> None:
        details_window = tk.Toplevel(self)
        details_window.title(f"Mapa {map_index + 1} - {map_entry.get('map_name', '')}")
        details_window.transient(self)
        details_window.configure(bg="#0b0b0c")
        details_window.geometry("1200x820")
        details_window.minsize(1040, 720)
        details_window.match_details_fullscreen = False
        details_window.background_image_ref = None
        details_window.background_refresh_job = None
        details_window.map_name_for_background = str(map_entry.get("map_name", "")).strip()
        background_label = tk.Label(details_window, bg="#050607")
        background_label.place(x=0, y=0, relwidth=1, relheight=1)
        details_window.background_label = background_label
        self._update_match_details_background(details_window)
        details_window.bind("<F11>", lambda _event, window=details_window: self._toggle_match_details_fullscreen(window))
        details_window.bind("<Escape>", lambda _event, window=details_window: self._exit_match_details_fullscreen(window))
        details_window.bind("<Configure>", lambda _event, window=details_window: self._schedule_match_details_background_refresh(window))

        container = tk.Frame(details_window, bg="#0b0b0c", padx=22, pady=22)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)
        team_scores = self._get_map_entry_team_scores(match, map_entry)
        map_teams = self._get_map_entry_team_payloads(match, map_entry)
        left_mvp = self._get_top_player_from_team_payload(map_teams[0])
        right_mvp = self._get_top_player_from_team_payload(map_teams[1])

        scoreboard = tk.Frame(container, bg="#1a121c", highlightthickness=1, highlightbackground="#4b1ea8", padx=18, pady=16)
        scoreboard.grid(row=0, column=0, sticky="ew")
        scoreboard.columnconfigure((0, 4), weight=1)
        scoreboard.columnconfigure(2, weight=0)
        self._build_broadcast_score_team(scoreboard, 0, match["team1"], team_scores[0], left_mvp.get("display_name", ""), align="w")
        center_badge = tk.Frame(scoreboard, bg="#2b2230", padx=30, pady=10)
        center_badge.grid(row=0, column=2, padx=20)
        tk.Label(center_badge, text=str(map_entry.get("map_name", "")).strip() or "MAPA", bg="#2b2230", fg="#f3f3f3", font=(self.button_font_family, 22)).pack()
        tk.Label(center_badge, text=f"MAPA {map_index + 1}", bg="#2b2230", fg="#c6b4ff", font=(self.title_font_family, 10, "bold")).pack(pady=(4, 0))
        self._build_broadcast_score_team(scoreboard, 4, match["team2"], team_scores[1], right_mvp.get("display_name", ""), align="e")

        duel_card = tk.Frame(container, bg="#140f18", highlightthickness=1, highlightbackground="#4b1ea8")
        duel_card.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        duel_card.columnconfigure((0, 2), weight=1)
        duel_card.columnconfigure(1, weight=0)
        self._build_broadcast_mvp_side(duel_card, 0, match["team1"], left_mvp, side="left")
        center_stats = tk.Frame(duel_card, bg="#17131b", padx=24, pady=22)
        center_stats.grid(row=0, column=1, sticky="ns")
        self._build_broadcast_center_stats(center_stats, left_mvp, right_mvp)
        self._build_broadcast_mvp_side(duel_card, 2, match["team2"], right_mvp, side="right")

        bottom = tk.Frame(container, bg="#0b0b0c")
        bottom.grid(row=2, column=0, sticky="nsew", pady=(14, 0))
        bottom.columnconfigure(1, weight=1)
        bottom.rowconfigure(0, weight=1)

        preview_card = tk.Frame(bottom, bg="#15171b", highlightthickness=1, highlightbackground="#4b1ea8", padx=12, pady=12)
        preview_card.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        map_name = str(map_entry.get("map_name", "")).strip()
        preview_image = self._load_map_cover_image(map_name, (230, 340), grayscale=False) if map_name else None
        if preview_image:
            preview_label = tk.Label(preview_card, image=preview_image, bg="#15171b")
            preview_label.image = preview_image
            preview_label.pack()
            details_window.map_preview_ref = preview_image
        else:
            tk.Frame(preview_card, bg="#1a1d21", width=230, height=340).pack()
        tk.Label(preview_card, text=map_name or "MAPA", bg="#6c23ff", fg="#f3f3f3", font=(self.button_font_family, 18), padx=12, pady=6).pack(anchor="w", pady=(10, 0))

        table_card = tk.Frame(bottom, bg="#15171b", highlightthickness=1, highlightbackground="#4b1ea8", padx=16, pady=16)
        table_card.grid(row=0, column=1, sticky="nsew")
        table_card.columnconfigure((0, 1, 2), weight=1)
        header = tk.Frame(table_card, bg="#15171b")
        header.grid(row=0, column=0, columnspan=3, sticky="ew")
        tk.Label(header, text=match["team1"], bg="#15171b", fg="#f3f3f3", font=(self.button_font_family, 18)).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="KD   ACS", bg="#15171b", fg="#b9a8ef", font=(self.title_font_family, 11, "bold")).grid(row=0, column=1, sticky="ew")
        tk.Label(header, text=match["team2"], bg="#15171b", fg="#f3f3f3", font=(self.button_font_family, 18)).grid(row=0, column=2, sticky="e")
        self._build_broadcast_roster_rows(table_card, 1, map_teams[0], map_teams[1])

    def _build_broadcast_score_team(self, parent: tk.Widget, column_index: int, team_name: str, score: str, subtitle: str, align: str = "w") -> None:
        team_block = tk.Frame(parent, bg="#1a121c")
        team_block.grid(row=0, column=column_index, sticky="nsew")
        anchor = "w" if align == "w" else "e"
        justify = "left" if align == "w" else "right"
        tk.Label(team_block, text=team_name, bg="#1a121c", fg="#f3f3f3", anchor=anchor, justify=justify, font=(self.button_font_family, 28)).pack(anchor=anchor)
        tk.Label(team_block, text=subtitle or "MVP pendente", bg="#1a121c", fg="#d6bc5c", anchor=anchor, justify=justify, font=(self.title_font_family, 10, "bold")).pack(anchor=anchor, pady=(4, 0))
        score_label = tk.Label(parent, text=score or "-", bg="#1a121c", fg="#f3f3f3", font=(self.button_font_family, 52))
        score_label.grid(row=0, column=1 if column_index == 0 else 3, padx=18)

    def _build_broadcast_mvp_side(self, parent: tk.Widget, column_index: int, team_name: str, player: dict, side: str) -> None:
        side_frame = tk.Frame(parent, bg="#140f18", padx=18, pady=18)
        side_frame.grid(row=0, column=column_index, sticky="nsew")
        anchor = "w" if side == "left" else "e"
        ribbon_anchor = "nw" if side == "left" else "ne"
        ribbon = tk.Label(side_frame, text="MVP", bg="#6c23ff", fg="#f3f3f3", font=(self.button_font_family, 16), padx=14, pady=5)
        ribbon.pack(anchor=ribbon_anchor)
        tk.Label(side_frame, text=team_name, bg="#140f18", fg="#b7bfd0", anchor=anchor, font=(self.title_font_family, 10, "bold")).pack(anchor=anchor, pady=(12, 0))
        tk.Label(side_frame, text=player.get("display_name", "MVP"), bg="#140f18", fg="#f3f3f3", anchor=anchor, justify="left" if side == "left" else "right", font=(self.button_font_family, 28)).pack(anchor=anchor, pady=(8, 0))
        tk.Label(side_frame, text=f"ACS {player.get('acs', '-')}", bg="#140f18", fg="#d8dbe3", anchor=anchor, font=(self.title_font_family, 11, "bold")).pack(anchor=anchor, pady=(8, 0))

    def _build_broadcast_center_stats(self, parent: tk.Widget, left_player: dict, right_player: dict) -> None:
        stat_rows = [
            (f"{left_player.get('kills', '-')}/{left_player.get('deaths', '-')}", "KD", f"{right_player.get('kills', '-')}/{right_player.get('deaths', '-')}"),
            (str(left_player.get("acs", "-")), "ACS", str(right_player.get("acs", "-"))),
            (str(left_player.get("assists", "-")), "ASSISTS", str(right_player.get("assists", "-"))),
        ]
        for index, (left_value, label, right_value) in enumerate(stat_rows):
            tk.Label(parent, text=left_value, bg="#17131b", fg="#f3f3f3", font=(self.button_font_family, 26)).grid(row=index, column=0, sticky="e", padx=(0, 22), pady=6)
            tk.Label(parent, text=label, bg="#17131b", fg="#d0d3d8", font=(self.title_font_family, 13, "bold")).grid(row=index, column=1, pady=6)
            tk.Label(parent, text=right_value, bg="#17131b", fg="#f3f3f3", font=(self.button_font_family, 26)).grid(row=index, column=2, sticky="w", padx=(22, 0), pady=6)

    def _build_broadcast_roster_rows(self, parent: tk.Widget, start_row: int, left_payload: dict, right_payload: dict) -> None:
        left_players = [player for player in left_payload.get("players", []) if isinstance(player, dict)]
        right_players = [player for player in right_payload.get("players", []) if isinstance(player, dict)]
        total_rows = max(len(left_players), len(right_players), 5)
        for row_offset in range(total_rows):
            left_player = left_players[row_offset] if row_offset < len(left_players) else {}
            right_player = right_players[row_offset] if row_offset < len(right_players) else {}
            row_frame = tk.Frame(parent, bg="#121418")
            row_frame.grid(row=start_row + row_offset, column=0, columnspan=3, sticky="ew", pady=1)
            row_frame.columnconfigure((0, 2), weight=1)
            row_frame.columnconfigure(1, weight=0)
            tk.Label(row_frame, text=left_player.get("display_name", "-"), bg="#121418", fg="#e3e6ec", anchor="w", font=(self.title_font_family, 10, "bold"), padx=10, pady=9).grid(row=0, column=0, sticky="ew")
            tk.Label(row_frame, text=self._format_broadcast_player_stats(left_player, right_player), bg="#17131b", fg="#f3f3f3", font=(self.title_font_family, 10, "bold"), padx=14, pady=9).grid(row=0, column=1, sticky="ew")
            tk.Label(row_frame, text=right_player.get("display_name", "-"), bg="#121418", fg="#e3e6ec", anchor="e", font=(self.title_font_family, 10, "bold"), padx=10, pady=9).grid(row=0, column=2, sticky="ew")

    def _format_broadcast_player_stats(self, left_player: dict, right_player: dict) -> str:
        left_text = f"{left_player.get('kills', '-')}/{left_player.get('deaths', '-')}  {left_player.get('acs', '-')}"
        right_text = f"{right_player.get('kills', '-')}/{right_player.get('deaths', '-')}  {right_player.get('acs', '-')}"
        return f"{left_text}     {right_text}"

    def _get_top_player_from_team_payload(self, payload: dict) -> dict:
        players = [player for player in payload.get("players", []) if isinstance(player, dict)]
        if not players:
            return {"display_name": "MVP pendente", "acs": "-", "kills": "-", "deaths": "-", "assists": "-"}
        return max(players, key=lambda player: (self._safe_int(player.get("acs")), self._safe_int(player.get("kills"))))

    def _get_map_entry_team_payloads(self, match: dict, map_entry: dict) -> tuple[dict, dict]:
        team_map = {}
        teams_payload = map_entry.get("teams", []) if isinstance(map_entry, dict) else []
        for payload in teams_payload:
            if isinstance(payload, dict):
                team_map[str(payload.get("name", ""))] = payload
        return team_map.get(match["team1"], {}), team_map.get(match["team2"], {})

    def _get_map_entry_team_scores(self, match: dict, map_entry: dict) -> tuple[str, str]:
        team_one_payload, team_two_payload = self._get_map_entry_team_payloads(match, map_entry)
        team_one_score = str(team_one_payload.get("score", "") or match.get("team1_score", "") or "-")
        team_two_score = str(team_two_payload.get("score", "") or match.get("team2_score", "") or "-")
        return team_one_score, team_two_score

    def _get_match_background_map_name(self, match: dict) -> str:
        map_entries = self._get_match_map_entries(match)
        for map_entry in reversed(map_entries):
            map_name = str(map_entry.get("map_name", "")).strip()
            if map_name:
                return map_name
        return match.get("map_name", "").strip() or self._get_official_meta(match, "map_name")

    def _toggle_match_details_fullscreen(self, window: tk.Toplevel) -> None:
        next_state = not bool(getattr(window, "match_details_fullscreen", False))
        window.match_details_fullscreen = next_state
        window.attributes("-fullscreen", next_state)

    def _exit_match_details_fullscreen(self, window: tk.Toplevel) -> None:
        if bool(getattr(window, "match_details_fullscreen", False)):
            self._toggle_match_details_fullscreen(window)

    def _schedule_match_details_background_refresh(self, window: tk.Toplevel) -> None:
        if not getattr(window, "map_name_for_background", ""):
            return
        existing_job = getattr(window, "background_refresh_job", None)
        if existing_job:
            window.after_cancel(existing_job)
        window.background_refresh_job = window.after(70, lambda: self._update_match_details_background(window))

    def _update_match_details_background(self, window: tk.Toplevel) -> None:
        map_name = str(getattr(window, "map_name_for_background", "")).strip()
        if not map_name or not hasattr(window, "background_label"):
            return
        width = max(window.winfo_width(), 960)
        height = max(window.winfo_height(), 680)
        background_image = self._load_map_cover_image(map_name, (width, height), grayscale=False)
        if not background_image:
            return
        window.background_label.configure(image=background_image)
        window.background_image_ref = background_image
        window.background_label.lower()
        window.background_refresh_job = None

    def _toggle_app_fullscreen(self, _event=None) -> str:
        self.app_fullscreen = not self.app_fullscreen
        self.attributes("-fullscreen", self.app_fullscreen)
        return "break"

    def _exit_app_fullscreen(self, _event=None) -> str | None:
        if self.app_fullscreen:
            self.app_fullscreen = False
            self.attributes("-fullscreen", False)
            return "break"
        return None

    def _build_public_match_hero_team(self, parent: tk.Widget, team_name: str, column_index: int) -> None:
        block = tk.Frame(parent, bg="#15171b")
        block.grid(row=0, column=column_index, sticky="nsew")
        logo_image = self._load_public_match_logo(team_name, max_size=90)
        if logo_image:
            tk.Label(block, image=logo_image, bg="#15171b").pack(pady=(0, 10))
        tk.Label(block, text=team_name, bg="#15171b", fg="#f3f3f3", justify="center", wraplength=240, font=(self.title_font_family, 14, "bold")).pack()

    def _build_public_detail_stat(self, parent: tk.Widget, column_index: int, label: str, value: str) -> None:
        stat_block = tk.Frame(parent, bg="#15171b")
        stat_block.grid(row=0, column=column_index, sticky="nsew", padx=(0 if column_index == 0 else 10, 0))
        tk.Label(stat_block, text=label.upper(), bg="#15171b", fg="#89919b", font=(self.button_font_family, 16)).pack(anchor="w")
        tk.Label(stat_block, text=value, bg="#15171b", fg="#f3f3f3", justify="left", wraplength=220, font=(self.title_font_family, 11, "bold")).pack(anchor="w", pady=(8, 0))

    def _build_public_match_detail_team_card(self, parent: tk.Widget, column_index: int, team_name: str, payload: dict) -> None:
        team_card = tk.Frame(parent, bg="#15171b", highlightthickness=1, highlightbackground="#2a2d32", padx=18, pady=18)
        team_card.grid(row=0, column=column_index, sticky="nsew", padx=(0, 7) if column_index == 0 else (7, 0))
        team_card.columnconfigure(0, weight=1)

        header = tk.Frame(team_card, bg="#15171b")
        header.grid(row=0, column=0, sticky="ew")
        logo_image = self._load_public_match_logo(team_name, max_size=60)
        if logo_image:
            tk.Label(header, image=logo_image, bg="#15171b").pack(side="left", padx=(0, 10))
        title_block = tk.Frame(header, bg="#15171b")
        title_block.pack(side="left", fill="x", expand=True)
        tk.Label(title_block, text=team_name, bg="#15171b", fg="#f3f3f3", font=(self.title_font_family, 13, "bold")).pack(anchor="w")
        score_text = str(payload.get("score", "")).strip() if isinstance(payload, dict) else ""
        if score_text:
            tk.Label(title_block, text=f"Rounds: {score_text}", bg="#15171b", fg="#9ca4ae", font=(self.title_font_family, 10)).pack(anchor="w", pady=(4, 0))

        table = tk.Frame(team_card, bg="#15171b")
        table.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        headers = ["Jogador", "ACS", "K", "D", "A"]
        for index, label in enumerate(headers):
            tk.Label(table, text=label, bg="#1d2025", fg="#f3f3f3", font=(self.title_font_family, 9, "bold"), padx=8, pady=6).grid(row=0, column=index, sticky="ew", padx=1, pady=1)
            table.columnconfigure(index, weight=1 if index == 0 else 0)

        players = payload.get("players", []) if isinstance(payload, dict) else []
        if players:
            for row_offset, player in enumerate(players, start=1):
                tk.Label(table, text=player.get("display_name", "-"), bg="#181a1e", fg="#d8dde4", anchor="w", padx=8, pady=6, font=(self.title_font_family, 9)).grid(row=row_offset, column=0, sticky="ew", padx=1, pady=1)
                tk.Label(table, text=str(player.get("acs", "-")), bg="#181a1e", fg="#d8dde4", padx=8, pady=6, font=(self.title_font_family, 9)).grid(row=row_offset, column=1, sticky="ew", padx=1, pady=1)
                tk.Label(table, text=str(player.get("kills", "-")), bg="#181a1e", fg="#d8dde4", padx=8, pady=6, font=(self.title_font_family, 9)).grid(row=row_offset, column=2, sticky="ew", padx=1, pady=1)
                tk.Label(table, text=str(player.get("deaths", "-")), bg="#181a1e", fg="#d8dde4", padx=8, pady=6, font=(self.title_font_family, 9)).grid(row=row_offset, column=3, sticky="ew", padx=1, pady=1)
                tk.Label(table, text=str(player.get("assists", "-")), bg="#181a1e", fg="#d8dde4", padx=8, pady=6, font=(self.title_font_family, 9)).grid(row=row_offset, column=4, sticky="ew", padx=1, pady=1)
            return

        fallback_players = [player for player in self._get_team_profile_players(team_name) if player]
        for row_offset, player_name in enumerate(fallback_players or ["Sem lineup oficial"], start=1):
            tk.Label(table, text=player_name, bg="#181a1e", fg="#d8dde4", anchor="w", padx=8, pady=6, font=(self.title_font_family, 9)).grid(row=row_offset, column=0, columnspan=5, sticky="ew", padx=1, pady=1)

    def _build_admin_maps_tab(self) -> None:
        _shell, _canvas, content = self._create_scrollable_container(self.admin_maps_tab, bg="#f4f6f8", show_scrollbar=True)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)

        control_card = ttk.LabelFrame(content, text="Controle do draft", padding=16)
        control_card.grid(row=0, column=0, sticky="ew")
        for column_index in range(6):
            control_card.columnconfigure(column_index, weight=1)

        self.map_team_one_var = tk.StringVar()
        self.map_team_two_var = tk.StringVar()
        self.map_series_var = tk.StringVar(value=self._get_map_draft()["series_type"])
        self.map_current_step_var = tk.StringVar(value="Configure os times e inicie o draft.")

        ttk.Label(control_card, text="Primeira escolha").grid(row=0, column=0, sticky="w")
        self.map_team_one_combo = ttk.Combobox(control_card, state="readonly", textvariable=self.map_team_one_var)
        self.map_team_one_combo.grid(row=1, column=0, sticky="ew", pady=(6, 12), padx=(0, 8))
        self.map_team_one_combo.bind("<<ComboboxSelected>>", self._update_map_draft_settings)

        ttk.Label(control_card, text="Segunda escolha").grid(row=0, column=1, sticky="w")
        self.map_team_two_combo = ttk.Combobox(control_card, state="readonly", textvariable=self.map_team_two_var)
        self.map_team_two_combo.grid(row=1, column=1, sticky="ew", pady=(6, 12), padx=4)
        self.map_team_two_combo.bind("<<ComboboxSelected>>", self._update_map_draft_settings)

        ttk.Label(control_card, text="Serie").grid(row=0, column=2, sticky="w")
        self.map_series_combo = ttk.Combobox(control_card, state="readonly", textvariable=self.map_series_var, values=["MD1", "MD3", "MD5"])
        self.map_series_combo.grid(row=1, column=2, sticky="ew", pady=(6, 12), padx=4)
        self.map_series_combo.bind("<<ComboboxSelected>>", self._update_map_draft_settings)

        ttk.Button(control_card, text="Reiniciar draft", command=self._reset_map_draft, style="Primary.TButton").grid(row=1, column=3, sticky="ew", padx=4)
        ttk.Button(control_card, text="Atualizar catalogo", command=self._refresh_map_catalog).grid(row=1, column=4, sticky="ew", padx=4)

        ttk.Label(control_card, textvariable=self.map_current_step_var, style="Section.TLabel").grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))

        pool_card = ttk.LabelFrame(content, text="Pool manual", padding=16)
        pool_card.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        pool_card.columnconfigure(0, weight=1)
        ttk.Label(pool_card, text="Um mapa por linha. Apenas mapas existentes no catalogo local serao salvos.").grid(row=0, column=0, columnspan=3, sticky="w")
        self.map_pool_text = tk.Text(pool_card, height=5, bg="#101113", fg="#f3f3f3", insertbackground="#f3f3f3", relief="flat", bd=0, padx=10, pady=8, font=(self.title_font_family, 10))
        self.map_pool_text.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 10))
        ttk.Button(pool_card, text="Salvar pool", command=self._save_manual_map_pool, style="Primary.TButton").grid(row=2, column=0, sticky="w")
        ttk.Button(pool_card, text="Usar todos os mapas", command=self._use_all_maps_as_pool).grid(row=2, column=1, sticky="w", padx=(8, 0))
        self.map_pool_feedback_var = tk.StringVar(value="")
        ttk.Label(pool_card, textvariable=self.map_pool_feedback_var).grid(row=2, column=2, sticky="e")

        self._build_map_board(content, context_key="admin", interactive=True, row=2)
        self._sync_map_draft_controls_from_state()
        self._refresh_map_pool_editor()

    def _build_maps_tab(self) -> None:
        _shell, _canvas, content = self._create_scrollable_container(self.maps_tab, bg="#0b0b0c", show_scrollbar=False)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)

        header = tk.Frame(content, bg="#0b0b0c", padx=24, pady=16)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(
            header,
            text="SELECAO DE MAPAS",
            bg="#0b0b0c",
            fg="#f3f3f3",
            font=(self.button_font_family, 28),
            anchor="center",
            justify="center",
        ).pack()

        self._build_map_board(content, context_key="public", interactive=False, row=1)

    def _build_map_board(self, parent: tk.Widget, context_key: str, interactive: bool, row: int) -> None:
        shell = tk.Frame(parent, bg="#0b0b0c")
        shell.grid(row=row, column=0, sticky="nsew", pady=(12, 0))
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        canvas = tk.Canvas(shell, bg="#0b0b0c", highlightthickness=0, bd=0, height=430)
        canvas.grid(row=0, column=0, sticky="nsew")
        if context_key == "public":
            canvas.bind("<Configure>", lambda _event: self._refresh_map_views())
        self.map_board_contexts[context_key] = {
            "canvas": canvas,
            "interactive": interactive,
            "image_refs": [],
            "layout": "columns" if context_key == "public" else "grid",
            "has_rendered_once": False,
        }

    def _refresh_map_catalog(self) -> None:
        self.all_map_catalog = self._load_local_map_catalog()
        self._normalize_map_pool()
        self.map_image_cache = {}
        self.map_catalog = self._build_fallback_map_catalog()
        self.map_catalog_loaded = True
        self._refresh_map_pool_editor()
        self._refresh_map_views()

    def _sync_map_draft_controls_from_state(self) -> None:
        if not hasattr(self, "map_team_one_combo"):
            return
        choices = self._get_map_team_choices()
        labels = [label for label, _slot in choices]
        slot_lookup = {label: slot for label, slot in choices}
        self.map_team_one_combo["values"] = labels
        self.map_team_two_combo["values"] = labels

        draft = self._get_map_draft()
        team_one = self._get_team_profile_by_slot(draft["team_one_slot"])
        team_two = self._get_team_profile_by_slot(draft["team_two_slot"])
        team_one_label = team_one.get("name", "").strip() or (labels[0] if labels else "")
        team_two_label = team_two.get("name", "").strip() or (labels[1] if len(labels) > 1 else (labels[0] if labels else ""))
        self.map_team_one_var.set(team_one_label)
        self.map_team_two_var.set(team_two_label)
        self.map_series_var.set(draft["series_type"])

        if team_one_label in slot_lookup:
            draft["team_one_slot"] = slot_lookup[team_one_label]
        if team_two_label in slot_lookup:
            draft["team_two_slot"] = slot_lookup[team_two_label]

    def _refresh_map_pool_editor(self) -> None:
        if not hasattr(self, "map_pool_text"):
            return
        current_pool = self._get_map_pool()
        current_text = self.map_pool_text.get("1.0", "end").strip()
        next_text = "\n".join(current_pool)
        if current_text != next_text:
            self.map_pool_text.delete("1.0", "end")
            self.map_pool_text.insert("1.0", next_text)
        if hasattr(self, "map_pool_feedback_var"):
            available_count = len(self.all_map_catalog)
            self.map_pool_feedback_var.set(f"Pool atual: {len(current_pool)} | Catalogo: {available_count}")

    def _save_manual_map_pool(self) -> None:
        if not hasattr(self, "map_pool_text"):
            return
        raw_text = self.map_pool_text.get("1.0", "end")
        requested_names: list[str] = []
        for chunk in raw_text.replace(",", "\n").splitlines():
            map_name = chunk.strip()
            if map_name and map_name not in requested_names:
                requested_names.append(map_name)

        available_names = {item["name"] for item in self.all_map_catalog}
        valid_names = [name for name in requested_names if name in available_names]
        invalid_names = [name for name in requested_names if name not in available_names]
        if not valid_names:
            messagebox.showwarning("Mapas", "Nenhum mapa valido foi informado para a pool.")
            return

        self.state["map_pool"] = valid_names
        self._get_map_draft()["actions"] = []
        self._save_state()
        self.map_image_cache = {}
        self.map_catalog = self._build_fallback_map_catalog()
        self._refresh_map_pool_editor()
        self._refresh_map_views()
        if invalid_names:
            messagebox.showwarning("Mapas", "Alguns nomes foram ignorados porque nao existem no catalogo local:\n\n" + "\n".join(invalid_names))

    def _use_all_maps_as_pool(self) -> None:
        self.state["map_pool"] = [item["name"] for item in self.all_map_catalog]
        self._get_map_draft()["actions"] = []
        self._save_state()
        self.map_image_cache = {}
        self.map_catalog = self._build_fallback_map_catalog()
        self._refresh_map_pool_editor()
        self._refresh_map_views()

    def _update_map_draft_settings(self, _event=None) -> None:
        draft = self._get_map_draft()
        choices = dict(self._get_map_team_choices())
        if self.map_team_one_var.get() in choices:
            draft["team_one_slot"] = choices[self.map_team_one_var.get()]
        if self.map_team_two_var.get() in choices:
            draft["team_two_slot"] = choices[self.map_team_two_var.get()]
        draft["series_type"] = self.map_series_var.get() if self.map_series_var.get() in {"MD1", "MD3", "MD5"} else "MD3"
        draft["actions"] = []
        self._save_state()
        self._refresh_map_views()

    def _reset_map_draft(self, save_state: bool = True) -> None:
        draft = self._get_map_draft()
        draft["actions"] = []
        if save_state:
            self._save_state()
        self._refresh_map_views()

    def _get_map_status_payload(self) -> tuple[dict[str, dict], dict | None]:
        draft = self._get_map_draft()
        sequence = self._get_map_sequence(draft["series_type"])
        statuses = {
            map_item["name"]: {
                "state": "available",
                "team_slot": None,
                "team_name": "",
                "team_logo": "",
                "action_type": "",
                "step_label": "",
            }
            for map_item in self.map_catalog
        }
        choices = {slot: self._get_team_profile_by_slot(slot) for _label, slot in self._get_map_team_choices()}
        valid_actions: list[dict] = []
        for action in draft.get("actions", []):
            map_name = action.get("map_name", "")
            if map_name not in statuses:
                continue
            profile = choices.get(action.get("team_slot"), self._blank_team_profile(0))
            statuses[map_name] = {
                "state": "picked" if action.get("action_type") == "pick" else "banned",
                "team_slot": action.get("team_slot"),
                "team_name": profile.get("name", "") or f"Time {action.get('team_slot', 0) + 1}",
                "team_logo": profile.get("logo_path", ""),
                "action_type": action.get("action_type", ""),
                "step_label": action.get("label", ""),
            }
            valid_actions.append(action)

        draft["actions"] = valid_actions
        remaining_maps = [map_name for map_name, payload in statuses.items() if payload["state"] == "available"]
        next_step = sequence[len(valid_actions)] if len(valid_actions) < len(sequence) else None

        if next_step is None and len(remaining_maps) == 1:
            decider_name = remaining_maps[0]
            team_one_profile = self._get_team_profile_by_slot(draft["team_one_slot"])
            statuses[decider_name] = {
                "state": "decider",
                "team_slot": None,
                "team_name": f"Decider | {team_one_profile.get('name', '') or 'Serie'} x {self._get_team_profile_by_slot(draft['team_two_slot']).get('name', '') or 'Serie'}",
                "team_logo": "",
                "action_type": "decider",
                "step_label": "DECIDER",
            }

        return statuses, next_step

    def _get_map_step_label(self, step: dict) -> str:
        draft = self._get_map_draft()
        slot = draft["team_one_slot"] if step["team"] == 0 else draft["team_two_slot"]
        team_name = self._get_team_profile_by_slot(slot).get("name", "").strip() or f"Time {slot + 1}"
        action_label = "banir" if step["type"] == "ban" else "escolher"
        return f"Agora: {team_name} vai {action_label} um mapa"

    def _refresh_map_views(self) -> None:
        self._sync_map_draft_controls_from_state()
        statuses, next_step = self._get_map_status_payload()
        current_decider = next((name for name, payload in statuses.items() if payload.get("state") == "decider"), "")
        if not current_decider:
            self.public_map_revealed_decider = ""
            self.public_map_pending_decider = ""
        if hasattr(self, "map_current_step_var"):
            self.map_current_step_var.set(self._get_map_step_label(next_step) if next_step else "Draft concluido.")
        if hasattr(self, "public_map_status_var"):
            self.public_map_status_var.set(self._get_map_step_label(next_step) if next_step else "Draft concluido. O ultimo mapa restante virou o Decider.")
        for context_key in list(self.map_board_contexts):
            self._refresh_map_board(context_key, statuses=statuses, next_step=next_step)

    def _refresh_map_board(self, context_key: str, statuses: dict | None = None, next_step: dict | None = None) -> None:
        context = self.map_board_contexts.get(context_key)
        if not context:
            return
        canvas: tk.Canvas = context["canvas"]
        canvas.delete("all")
        for job_id in context.get("animation_jobs", []):
            try:
                self.after_cancel(job_id)
            except Exception:
                pass
        context["animation_jobs"] = []
        context["image_refs"] = []
        statuses = statuses or self._get_map_status_payload()[0]
        if context.get("layout") == "columns":
            canvas_width = max(canvas.winfo_width(), 980)
            canvas_height = max(canvas.winfo_height(), 520)
            margin_x = 18
            margin_y = 8
            gap = 8
            column_count = 7
            usable_width = canvas_width - (margin_x * 2) - gap * max(column_count - 1, 0)
            column_width = max(92, int(usable_width / column_count))
            board_width = column_width * column_count + gap * max(column_count - 1, 0)
            start_x = max((canvas_width - board_width) / 2, margin_x)
            column_height = max(canvas_height - (margin_y * 2), 360)
            title_font_size = max(18, int(column_width * 0.17))
            top_font_size = max(8, int(column_width * 0.06))
            bottom_font_size = max(8, int(column_width * 0.055))
            team_name_font_size = max(8, int(column_width * 0.055))
            team_logo_size = max(24, int(column_width * 0.22))
            decider_name = next((name for name, payload in statuses.items() if payload.get("state") == "decider"), "")
            previous_map_names = {item[0] for item in self.public_map_timeline_signature}
            include_decider = True
            if decider_name:
                include_decider = not (
                    self.public_map_timeline_signature
                    and decider_name not in previous_map_names
                    and self.public_map_pending_decider != decider_name
                    and self.public_map_revealed_decider != decider_name
                )
            display_items = self._get_public_map_display_items(statuses, include_decider=include_decider)
            display_signature = tuple(
                (
                    item["map_name"],
                    str(item.get("state", "")),
                    str(item.get("action_type", "")),
                    str(item.get("team_name", "")),
                )
                for item in display_items
            )
            latest_bounds: tuple[float, float, float, float] | None = None
            latest_action_type = ""

            for index in range(column_count):
                if index >= len(display_items):
                    continue
                item = display_items[index]
                map_name = item["map_name"]
                tile_x = start_x + index * (column_width + gap)
                tile_y = margin_y
                state = item
                action_type = state.get("action_type", "")
                image = self._load_map_cover_image(map_name, (column_width, column_height), grayscale=state.get("state") == "banned")
                if image:
                    context["image_refs"].append(image)
                    canvas.create_image(tile_x + (column_width / 2), tile_y + (column_height / 2), image=image)
                else:
                    canvas.create_rectangle(tile_x, tile_y, tile_x + column_width, tile_y + column_height, outline="", fill="#16181b")

                if state.get("state") == "picked":
                    canvas.create_rectangle(tile_x, tile_y, tile_x + column_width, tile_y + column_height, outline="#7d35ff", width=3)
                elif state.get("state") == "decider":
                    canvas.create_rectangle(tile_x, tile_y, tile_x + column_width, tile_y + column_height, outline="#f3b41b", width=3)

                top_fill = "#6c23ff" if action_type == "pick" else ("#6b6f77" if action_type == "ban" else "#7c5a11")
                canvas.create_rectangle(tile_x, tile_y, tile_x + column_width, tile_y + 28, outline="", fill=top_fill)
                canvas.create_text(
                    tile_x + (column_width / 2),
                    tile_y + 14,
                    text=state.get("step_label", "DECIDER") or "DECIDER",
                    fill="#f5f5f5",
                    font=(self.title_font_family, top_font_size, "bold"),
                )

                overlay_height = max(118, int(column_height * 0.22))
                overlay_top = tile_y + int((column_height - overlay_height) / 2)
                overlay_bottom = overlay_top + overlay_height
                team_logo = self._load_logo_image(state.get("team_logo", ""), max_size=team_logo_size)
                center_x = tile_x + (column_width / 2)
                if team_logo:
                    context["image_refs"].append(team_logo)
                    canvas.create_image(center_x, overlay_top + max(24, int(overlay_height * 0.28)), image=team_logo)
                name_y = overlay_top + max(70, int(overlay_height * 0.70))
                for shadow_dx, shadow_dy in ((1, 1),):
                    canvas.create_text(
                        center_x + shadow_dx,
                        name_y + shadow_dy,
                        text=(state.get("team_name", "") or "DECIDER").upper(),
                        fill="#050607",
                        width=column_width - 18,
                        justify="center",
                        font=(self.title_font_family, team_name_font_size, "bold"),
                    )
                canvas.create_text(
                    center_x,
                    name_y,
                    text=(state.get("team_name", "") or "DECIDER").upper(),
                    fill="#f5f5f5",
                    width=column_width - 18,
                    justify="center",
                    font=(self.title_font_family, team_name_font_size, "bold"),
                )

                canvas.create_rectangle(tile_x, tile_y + column_height - 72, tile_x + column_width, tile_y + column_height, outline="", fill="#111214")
                canvas.create_text(
                    tile_x + (column_width / 2),
                    tile_y + column_height - 40,
                    text=map_name.upper(),
                    fill="#f4f4f4",
                    width=column_width - 12,
                    font=(self.button_font_family, title_font_size),
                )
                canvas.create_text(
                    tile_x + (column_width / 2),
                    tile_y + column_height - 14,
                    text=("Escolha" if action_type == "pick" else ("Banimento" if action_type == "ban" else "Decider")),
                    fill="#d5d8dc",
                    width=column_width - 12,
                    font=(self.title_font_family, bottom_font_size, "bold"),
                )
                latest_bounds = (tile_x, tile_y, tile_x + column_width, tile_y + column_height)
                latest_action_type = action_type

            canvas.configure(height=column_height + (margin_y * 2), scrollregion=(0, 0, canvas_width, column_height + (margin_y * 2)))
            should_animate = bool(context.get("has_rendered_once")) and display_signature != self.public_map_timeline_signature
            if should_animate and latest_bounds and latest_action_type in {"pick", "ban", "decider"}:
                self._animate_map_reveal(canvas, context, latest_bounds, latest_action_type)
                if decider_name and not include_decider and self.public_map_pending_decider != decider_name:
                    self.public_map_pending_decider = decider_name
                    reveal_job = self.after(620, self._reveal_pending_public_decider)
                    context.setdefault("animation_jobs", []).append(reveal_job)
            self.public_map_timeline_signature = display_signature
            context["has_rendered_once"] = True
            return

        card_width = 212
        card_height = 290
        gap = 18
        start_x = 24
        start_y = 24
        map_count = max(len(self.map_catalog), 1)
        row_count = 2 if map_count > 5 else 1
        column_count = max(1, (map_count + row_count - 1) // row_count)
        canvas_width = max(canvas.winfo_width(), 720)
        usable_width = max(canvas_width - (start_x * 2), card_width)
        required_width = (column_count * card_width) + max(0, column_count - 1) * gap
        scale = min(1.0, usable_width / required_width)
        card_width = max(150, int(card_width * scale))
        card_height = max(210, int(card_height * scale))
        gap = max(12, int(gap * scale))
        start_x = max(16, int(start_x * scale))
        start_y = max(16, int(start_y * scale))
        header_height = max(30, int(38 * scale))
        image_height = max(104, int(160 * scale))
        footer_height = max(46, int(42 * scale))
        header_font_size = max(10, int(14 * scale))
        map_font_size = max(18, int(24 * scale))
        team_font_size = max(8, int(9 * scale))
        detail_font_size = max(8, int(9 * scale))
        fallback_brand_font = max(12, int(16 * scale))
        fallback_map_font = max(20, int(28 * scale))
        fallback_meta_font = max(8, int(10 * scale))
        team_logo_size = max(22, int(28 * scale))
        board_width = (column_count * card_width) + max(0, column_count - 1) * gap
        left_margin = max((canvas_width - board_width) / 2, start_x)

        for index, map_item in enumerate(self.map_catalog):
            map_name = map_item["name"]
            column = index % column_count
            row = index // column_count
            tile_x = left_margin + column * (card_width + gap)
            tile_y = start_y + row * (card_height + gap)
            state = statuses.get(map_name, {})
            action_type = state.get("action_type", "")
            header_fill = "#661fff" if action_type == "pick" else "#3d3f44"
            if state.get("state") == "decider":
                header_fill = "#c49011"
            canvas.create_rectangle(tile_x, tile_y, tile_x + card_width, tile_y + card_height, outline="#22252a", fill="#111214", width=2)
            canvas.create_rectangle(tile_x, tile_y, tile_x + card_width, tile_y + header_height, outline="", fill=header_fill)
            canvas.create_text(tile_x + card_width / 2, tile_y + (header_height / 2), text=state.get("step_label", "DISPONIVEL") or "DISPONIVEL", fill="#f6f6f6", font=(self.button_font_family, header_font_size))

            image_area_top = tile_y + header_height + max(4, int(4 * scale))
            image_area_bottom = image_area_top + image_height
            map_image = self._load_map_image(map_name, max_size=(card_width - 4, image_height - 8))
            if map_image:
                context["image_refs"].append(map_image)
                canvas.create_image(tile_x + card_width / 2, image_area_top + (image_height / 2), image=map_image)
            else:
                canvas.create_rectangle(tile_x + 2, image_area_top, tile_x + card_width - 2, image_area_bottom, outline="", fill="#18191b")
                canvas.create_rectangle(tile_x + 18, image_area_top + 16, tile_x + card_width - 18, image_area_top + 48, outline="#2f3238", fill="#121316")
                canvas.create_text(
                    tile_x + card_width / 2,
                    image_area_top + 32,
                    text="VCT DA RESENHA",
                    fill="#7e848f",
                    font=(self.button_font_family, fallback_brand_font),
                )
                canvas.create_text(
                    tile_x + card_width / 2,
                    image_area_top + (image_height * 0.52),
                    text=map_name.upper(),
                    fill="#f4f4f4",
                    width=card_width - 28,
                    font=(self.button_font_family, fallback_map_font),
                )
                canvas.create_text(
                    tile_x + card_width / 2,
                    image_area_top + image_height - 28,
                    text="Mapa oficial do draft",
                    fill="#8a8f98",
                    font=(self.title_font_family, fallback_meta_font),
                )

            if state.get("state") == "banned":
                canvas.create_rectangle(tile_x + 2, image_area_top, tile_x + card_width - 2, image_area_bottom, outline="", fill="#111111", stipple="gray50", tags=(f"map-anim:{context_key}:{map_name}",))
            elif state.get("state") == "picked":
                canvas.create_rectangle(tile_x + 2, image_area_top, tile_x + card_width - 2, image_area_bottom, outline="#7d35ff", width=3)
            elif state.get("state") == "decider":
                canvas.create_rectangle(tile_x + 2, image_area_top, tile_x + card_width - 2, image_area_bottom, outline="#f3b41b", width=3)

            title_y = image_area_bottom + max(18, int(22 * scale))
            canvas.create_text(tile_x + card_width / 2, title_y, text=map_name.upper(), fill="#f3f3f3", font=(self.button_font_family, map_font_size))
            footer_fill = "#6c23ff" if action_type == "pick" else ("#a32727" if action_type == "ban" else "#17181a")
            if state.get("state") == "decider":
                footer_fill = "#7c5a11"
            footer_top = tile_y + card_height - footer_height
            canvas.create_rectangle(tile_x, footer_top, tile_x + card_width, tile_y + card_height, outline="", fill=footer_fill)

            logo_image = self._load_logo_image(state.get("team_logo", ""), max_size=team_logo_size)
            if logo_image:
                context["image_refs"].append(logo_image)
                canvas.create_image(tile_x + max(20, int(20 * scale)), footer_top + (footer_height / 2), image=logo_image)
                text_anchor_x = tile_x + max(36, int(40 * scale))
            else:
                text_anchor_x = tile_x + max(12, int(14 * scale))
            canvas.create_text(
                text_anchor_x,
                footer_top + max(12, int(12 * scale)),
                anchor="w",
                text=(state.get("team_name", "") or "Aguardando acao")[:28],
                fill="#f5f5f5",
                width=card_width - 28,
                font=(self.title_font_family, team_font_size, "bold"),
            )
            canvas.create_text(
                text_anchor_x,
                footer_top + max(29, int(30 * scale)),
                anchor="w",
                text="Escolha" if action_type == "pick" else ("Banimento" if action_type == "ban" else ("Mapa decisivo" if state.get("state") == "decider" else "Disponivel")),
                fill="#e8e8e8",
                width=card_width - 28,
                font=(self.title_font_family, detail_font_size),
            )

            if context["interactive"] and state.get("state") == "available":
                tag = f"map-action:{map_name}"
                canvas.create_rectangle(tile_x, tile_y, tile_x + card_width, tile_y + card_height, outline="", fill="", tags=(tag,))
                canvas.tag_bind(tag, "<Button-1>", lambda _event, name=map_name: self._apply_map_action(name))

        board_height = start_y + row_count * card_height + max(0, row_count - 1) * gap + 24
        canvas.configure(height=board_height, scrollregion=(0, 0, canvas_width, board_height))

    def _animate_map_reveal(self, canvas: tk.Canvas, context: dict, bounds: tuple[float, float, float, float], action_type: str) -> None:
        flash_color = "#ff3b3b" if action_type == "ban" else ("#f3b41b" if action_type == "decider" else "#ffffff")
        flash_sequence = [True, False, True, False, True, False]
        x1, y1, x2, y2 = bounds

        def step(index: int) -> None:
            canvas.delete("map-reveal-flash")
            if index >= len(flash_sequence):
                return
            if flash_sequence[index]:
                canvas.create_rectangle(
                    x1,
                    y1,
                    x2,
                    y2,
                    outline=flash_color,
                    width=4,
                    fill=flash_color,
                    stipple="gray25",
                    tags=("map-reveal-flash",),
                )
            job_id = self.after(90, lambda: step(index + 1))
            context.setdefault("animation_jobs", []).append(job_id)

        step(0)

    def _reveal_pending_public_decider(self) -> None:
        if not self.public_map_pending_decider:
            return
        self.public_map_revealed_decider = self.public_map_pending_decider
        self.public_map_pending_decider = ""
        self._refresh_map_views()

    def _apply_map_action(self, map_name: str) -> None:
        statuses, next_step = self._get_map_status_payload()
        if map_name not in statuses or statuses[map_name]["state"] != "available" or not next_step:
            return

        draft = self._get_map_draft()
        team_slot = draft["team_one_slot"] if next_step["team"] == 0 else draft["team_two_slot"]
        profile = self._get_team_profile_by_slot(team_slot)
        action = {
            "map_name": map_name,
            "action_type": next_step["type"],
            "team_slot": team_slot,
            "label": ("PICK" if next_step["type"] == "pick" else "BAN"),
            "team_name": profile.get("name", "") or f"Time {team_slot + 1}",
        }
        draft.setdefault("actions", []).append(action)
        self._save_state()
        self._refresh_map_views()

    def _populate_widgets_from_state(self) -> None:
        self.cards_text.delete("1.0", "end")
        self.cards_text.insert("1.0", "\n".join(self.state.get("cards_pool", [])))
        self.team_count_var.set(str(self.state.get("team_count", 4)))
        self._populate_admin_bracket_from_profiles()
        self._populate_match_schedule_editor()
        self._refresh_admin_team_slots()
        self._refresh_admin_team_editor_from_state()
        self._refresh_portal_admin_dashboard()
        self._refresh_map_pool_editor()

    def _refresh_everything(self, preserve_selected_match: bool = False) -> None:
        team_names = self.state.get("registered_teams", [])
        bracket_size = self.state.get("bracket_size", 4)
        self._sync_team_draw_state()
        if len(team_names) == bracket_size and bracket_size in SUPPORTED_BRACKET_SIZES:
            self.resolved_matches = build_resolved_matches(
                team_names,
                bracket_size,
                self.state.get("match_results", {}),
                self.state.get("match_schedule", {}),
            )
        else:
            self.resolved_matches = []

        self._refresh_cards_panel()
        self._refresh_teams_tree()
        self._refresh_bracket_view()
        self._refresh_match_selector(preserve_selected_match=preserve_selected_match)
        self._refresh_map_views()
        self._refresh_public_matches_view()

    def _refresh_cards_panel(self) -> None:
        drawn_cards = self.state.get("drawn_cards", [])
        self.current_card_value.configure(text=drawn_cards[-1] if drawn_cards else "Nenhuma carta sorteada ainda.")
        self.drawn_cards_list.delete(0, "end")
        for card in reversed(drawn_cards):
            self.drawn_cards_list.insert("end", card)

    def _refresh_teams_tree(self) -> None:
        if not hasattr(self, "teams_public_grid"):
            return

        self.public_team_logo_refs = []
        for child in self.teams_public_grid.winfo_children():
            child.destroy()
        self._sync_team_draw_state()
        if self.public_teams_mode == "draw":
            self._build_public_team_draw_view()
            return
        if self.public_teams_mode == "list":
            self._render_public_team_list_view()
            return
        self._build_public_teams_menu_view()

    def _refresh_bracket_view(self) -> None:
        if not hasattr(self, "bracket_canvas"):
            return

        self.bracket_canvas.delete("all")
        self.bracket_card_items = {}
        self.bracket_logo_refs = []
        selected_match = self._get_match_by_id(self.state.get("selected_match_id", ""))
        if hasattr(self, "bracket_selected_title_var") and selected_match:
            self.bracket_selected_title_var.set(f"{selected_match['id']} - {selected_match['title']}")
            winner_label = selected_match["winner"] or "Sem vencedor definido"
            self.bracket_selected_meta_var.set(
                f"{selected_match['best_of']} | {selected_match['team1']} vs {selected_match['team2']} | {winner_label}"
            )
        elif hasattr(self, "bracket_selected_title_var"):
            self.bracket_selected_title_var.set("Nenhuma partida selecionada")
            self.bracket_selected_meta_var.set("Clique em um confronto da chave")

        if not self.resolved_matches:
            self.bracket_canvas.create_text(
                440,
                240,
                text="Monte a chave para visualizar o bracket",
                fill="#f3f3f3",
                font=(self.button_font_family, 26),
            )
            self.bracket_canvas.create_text(
                440,
                286,
                text="Use 4 ou 8 times no painel lateral.",
                fill="#8a8f98",
                font=(self.title_font_family, 11),
            )
            self.bracket_canvas.configure(scrollregion=(0, 0, 960, 560))
            return

        layout = self._get_bracket_layout(self.state.get("bracket_size", 4))
        canvas_width = max(self.bracket_canvas.winfo_width(), 1)
        canvas_height = max(self.bracket_canvas.winfo_height(), 1)
        scale_x = max(0.52, (canvas_width - 36) / layout["width"])
        scale_y = max(0.52, (canvas_height - 28) / layout["height"])
        scale = min(scale_x, scale_y, 0.98)
        card_size = (layout["card_size"][0] * scale, layout["card_size"][1] * scale)
        offset_x = max((canvas_width - (layout["width"] * scale)) / 2, 14)
        offset_y = max((canvas_height - (layout["height"] * scale)) / 2, 12)
        positions = {
            match_id: (offset_x + position[0] * scale, offset_y + position[1] * scale)
            for match_id, position in layout["positions"].items()
        }
        headers: list[dict] = []
        for header in layout["headers"]:
            header_item = {"title": header["title"], "y": offset_y + header["y"] * scale}
            if header.get("matches"):
                header_matches = [positions[match_id] for match_id in header["matches"] if match_id in positions]
                if header_matches:
                    centers = [match_position[0] + (card_size[0] / 2) for match_position in header_matches]
                    header_item["x"] = sum(centers) / len(centers)
                else:
                    header_item["x"] = offset_x + header.get("x", 0) * scale
            else:
                header_item["x"] = offset_x + header.get("x", 0) * scale
            headers.append(header_item)

        for header in headers:
            self._draw_bracket_header(header, scale)

        for match in self.resolved_matches:
            match_position = positions.get(match["id"])
            if match_position:
                self._draw_match_connectors(match, match_position, positions, card_size, scale)

        for match in self.resolved_matches:
            match_position = positions.get(match["id"])
            if match_position:
                self._draw_match_card(match, match_position, card_size, scale)

        self.bracket_canvas.configure(scrollregion=(0, 0, canvas_width, canvas_height))

    def _get_bracket_layout(self, bracket_size: int) -> dict:
        if bracket_size == 8:
            return {
                "width": 1980,
                "height": 990,
                "card_size": (294, 108),
                "headers": [
                    {"title": "Chave Superior - Rodada 1", "y": 42, "matches": ["UB1", "UB2", "UB3", "UB4"]},
                    {"title": "Chave Superior - Rodada 2", "y": 42, "matches": ["UB5", "UB6"]},
                    {"title": "Final da Chave Superior", "y": 42, "matches": ["UBF"]},
                    {"title": "Grande Final", "y": 42, "matches": ["GF"]},
                    {"title": "Chave Inferior - Rodada 1", "y": 672, "matches": ["LB1", "LB2"]},
                    {"title": "Chave Inferior - Rodada 2", "y": 672, "matches": ["LB3", "LB4"]},
                    {"title": "Semifinal Inferior", "y": 672, "matches": ["LB5"]},
                    {"title": "Final Inferior", "y": 672, "matches": ["LBF"]},
                ],
                "positions": {
                    "UB1": (24, 96),
                    "UB2": (24, 242),
                    "UB3": (24, 388),
                    "UB4": (24, 534),
                    "UB5": (446, 170),
                    "UB6": (446, 462),
                    "UBF": (1208, 316),
                    "GF": (1632, 500),
                    "LB1": (24, 720),
                    "LB2": (24, 866),
                    "LB3": (446, 720),
                    "LB4": (446, 866),
                    "LB5": (840, 793),
                    "LBF": (1208, 793),
                },
            }

        return {
            "width": 1460,
            "height": 804,
            "card_size": (314, 108),
            "headers": [
                {"title": "Chave Superior - Rodada 1", "y": 42, "matches": ["UB1", "UB2"]},
                {"title": "Final da Chave Superior", "y": 42, "matches": ["UBF"]},
                {"title": "Grande Final", "y": 42, "matches": ["GF"]},
                {"title": "Chave Inferior - Rodada 1", "y": 578, "matches": ["LB1"]},
                {"title": "Final Inferior", "y": 578, "matches": ["LBF"]},
            ],
            "positions": {
                "UB1": (26, 96),
                "UB2": (26, 278),
                "UBF": (546, 187),
                "GF": (1056, 404),
                "LB1": (26, 631),
                "LBF": (546, 631),
            },
        }

    def _draw_bracket_header(self, header: dict, scale: float) -> None:
        header_width = max(184 * scale, 148)
        x_pos = header["x"] - (header_width / 2)
        y_pos = header["y"]
        header_height = max(30 * scale, 24)
        self.bracket_canvas.create_rectangle(
            x_pos,
            y_pos,
            x_pos + header_width,
            y_pos + header_height,
            outline="#2d3035",
            fill="#24262a",
        )
        self.bracket_canvas.create_text(
            x_pos + (header_width / 2),
            y_pos + (header_height / 2),
            text=header["title"],
            fill="#e8eaed",
            font=(self.title_font_family, max(8, int(10.5 * scale)), "bold"),
        )

    def _get_team_profile_by_name(self, team_name: str) -> dict | None:
        normalized_name = team_name.strip().lower()
        if not normalized_name or normalized_name == "a definir":
            return None
        for profile in self._get_team_profiles():
            if profile.get("name", "").strip().lower() == normalized_name:
                return profile
        return None

    def _get_team_profile_players(self, team_name: str) -> list[str]:
        profile = self._get_team_profile_by_name(team_name)
        if not profile:
            return []
        return [str(player).strip() for player in profile.get("players", []) if str(player).strip()]

    def _get_team_riot_ids(self, team_name: str) -> list[str]:
        riot_ids: list[str] = []
        for player_name in self._get_team_profile_players(team_name):
            if parse_riot_id(player_name):
                riot_ids.append(player_name)
        return riot_ids

    def _get_team_captain_riot_id(self, team_name: str) -> str:
        players = self._get_team_profile_players(team_name)
        if not players:
            return ""
        captain = players[0].strip()
        return captain if parse_riot_id(captain) else ""

    def _normalize_player_identity(self, value: str) -> str:
        parsed_riot_id = parse_riot_id(value)
        if parsed_riot_id:
            return f"{parsed_riot_id[0].strip().lower()}#{parsed_riot_id[1].strip().lower()}"
        return str(value or "").strip().lower()

    def _get_player_validation_cache(self) -> dict[str, dict]:
        cache = self.state.setdefault("player_validation_cache", {})
        if not isinstance(cache, dict):
            self.state["player_validation_cache"] = {}
            cache = self.state["player_validation_cache"]
        return cache

    def _get_cached_player_validation(self, player_name: str) -> dict | None:
        cache = self._get_player_validation_cache()
        cached_payload = cache.get(self._normalize_player_identity(player_name))
        return cached_payload if isinstance(cached_payload, dict) else None

    def _store_cached_player_validation(self, player_name: str, payload: dict | None) -> None:
        if not isinstance(payload, dict):
            return
        compact_payload = {
            "name": str(payload.get("name") or payload.get("game_name") or payload.get("gameName") or "").strip(),
            "tag": str(payload.get("tag") or payload.get("tag_line") or payload.get("tagLine") or "").strip(),
            "region": str(payload.get("region") or payload.get("account_region") or payload.get("shard") or payload.get("affinity") or "").strip(),
        }
        self._get_player_validation_cache()[self._normalize_player_identity(player_name)] = compact_payload

    def _get_henrik_api_keys(self) -> list[str]:
        api_settings = self.state.get("api_settings", {})
        if isinstance(api_settings, dict):
            stored_keys = api_settings.get("henrik_api_keys", [])
            parsed_stored_keys = split_henrik_api_keys(stored_keys)
            if parsed_stored_keys:
                return parsed_stored_keys

            legacy_key = str(api_settings.get("henrik_api_key", "")).strip()
            if legacy_key:
                return split_henrik_api_keys(legacy_key)

        return get_henrik_api_keys()

    def _store_henrik_api_keys(self, api_keys: list[str]) -> None:
        api_settings = self.state.setdefault("api_settings", {})
        if not isinstance(api_settings, dict):
            self.state["api_settings"] = {}
            api_settings = self.state["api_settings"]

        normalized_keys = split_henrik_api_keys(api_keys)
        if normalized_keys:
            api_settings["henrik_api_keys"] = normalized_keys
            api_settings["henrik_api_key"] = normalized_keys[0]
            return

        api_settings.pop("henrik_api_keys", None)
        api_settings.pop("henrik_api_key", None)

    def _get_henrik_api_key_value(self) -> str:
        return ", ".join(self._get_henrik_api_keys())

    def _ensure_henrik_api_keys(self) -> list[str]:
        current_keys = self._get_henrik_api_keys()
        if current_keys:
            return current_keys

        entered_key = simpledialog.askstring(
            "Chave da API",
            "Cole uma ou mais chaves da API HenrikDev separadas por virgula para validar a partida oficialmente.",
            parent=self,
            show="*",
        )
        parsed_keys = split_henrik_api_keys(entered_key)
        if not parsed_keys:
            return []

        self._store_henrik_api_keys(parsed_keys)
        self._save_state()
        return parsed_keys

    def _save_henrik_api_key_from_form(self) -> None:
        entered_key = str(self.henrik_api_key_var.get() if hasattr(self, "henrik_api_key_var") else "")
        parsed_keys = split_henrik_api_keys(entered_key)
        if parsed_keys:
            self._store_henrik_api_keys(parsed_keys)
            self._save_state()
            self.official_lookup_status_var.set("Chaves HenrikDev salvas. A integracao oficial esta pronta para consultar.")
            self.henrik_api_key_var.set(", ".join(parsed_keys))
            self._set_app_feedback(f"{len(parsed_keys)} chave(s) HenrikDev salva(s) com sucesso.", tone="success")
            return
        self._store_henrik_api_keys([])
        self._save_state()
        self.official_lookup_status_var.set("Chaves HenrikDev removidas desta maquina.")
        self._set_app_feedback("Chaves HenrikDev removidas do app.", tone="success")

    def _safe_int(self, value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            cleaned_value = value.strip()
            if cleaned_value.isdigit():
                return int(cleaned_value)
        return 0

    def _get_series_target_wins(self, best_of: str) -> int:
        normalized_best_of = str(best_of or "MD1").strip().upper()
        if normalized_best_of == "MD5":
            return 3
        if normalized_best_of == "MD3":
            return 2
        return 1

    def _get_match_admin_status(self, match: dict) -> tuple[str, str, str]:
        if not match_can_receive_result(match):
            return "AGUARDANDO TIMES", "#3b4048", "#f1f3f5"
        if self._match_is_completed(match) and match.get("official_data"):
            return "OFICIAL", "#eef0f2", "#050607"
        if self._match_is_completed(match):
            return "CONCLUIDA", "#20242a", "#f1f3f5"
        team1_score = self._safe_int(match.get("team1_score", 0))
        team2_score = self._safe_int(match.get("team2_score", 0))
        if team1_score or team2_score:
            return "EM SERIE", "#262a30", "#f1f3f5"
        return "PRONTA", "#1c2026", "#f1f3f5"

    def _get_admin_match_option_label(self, match: dict) -> str:
        status_label, _bg, _fg = self._get_match_admin_status(match)
        return f"[{status_label}] {match_display_label(match)}"

    def _build_official_suggestion(self, match: dict) -> dict:
        official_payload = match.get("official_data", {}) if isinstance(match.get("official_data", {}), dict) else {}
        teams_payload = official_payload.get("teams", []) if isinstance(official_payload, dict) else []
        team_lookup = {team.get("name", ""): team for team in teams_payload if isinstance(team, dict)}
        team_one_payload = team_lookup.get(match.get("team1", ""), {})
        team_two_payload = team_lookup.get(match.get("team2", ""), {})
        winner_name = str(official_payload.get("winner", "")).strip()
        result_line = self._get_official_meta(match, "result_line") or match.get("official_result", "")
        score_one = str(team_one_payload.get("score", "")).strip() if isinstance(team_one_payload, dict) else ""
        score_two = str(team_two_payload.get("score", "")).strip() if isinstance(team_two_payload, dict) else ""
        map_name = self._get_official_meta(match, "map_name") or match.get("map_name", "")
        return {
            "winner": winner_name,
            "team1_score": score_one,
            "team2_score": score_two,
            "map_name": map_name,
            "result_line": result_line,
            "has_data": bool(winner_name or score_one or score_two or map_name or result_line),
        }

    def _apply_official_suggestion_to_form(self) -> None:
        match_id = self.state.get("selected_match_id", "")
        match = self._get_match_by_id(match_id)
        if not match:
            return
        suggestion = self._build_official_suggestion(match)
        if not suggestion.get("has_data"):
            self._set_app_feedback("Nenhuma sugestao oficial disponivel para aplicar.", tone="info")
            return
        if suggestion.get("winner"):
            self.match_winner_var.set(str(suggestion.get("winner", "")))
        if suggestion.get("team1_score"):
            self.team1_score_var.set(str(suggestion.get("team1_score", "")))
        if suggestion.get("team2_score"):
            self.team2_score_var.set(str(suggestion.get("team2_score", "")))
        if suggestion.get("map_name"):
            self.map_name_var.set(str(suggestion.get("map_name", "")))
        if suggestion.get("result_line"):
            self.official_result_var.set(str(suggestion.get("result_line", "")))
        self.official_lookup_status_var.set("Sugestao oficial aplicada ao formulario. Revise e salve quando quiser.")

    def _extract_official_players(self, official_match: dict) -> list[dict]:
        players_payload = official_match.get("players", {})
        raw_players: list[dict] = []
        if isinstance(players_payload, dict):
            candidates = players_payload.get("all_players") or players_payload.get("players") or []
            if isinstance(candidates, list):
                raw_players = [item for item in candidates if isinstance(item, dict)]
        elif isinstance(players_payload, list):
            raw_players = [item for item in players_payload if isinstance(item, dict)]

        metadata = official_match.get("metadata", {}) if isinstance(official_match.get("metadata", {}), dict) else {}
        rounds_played = max(self._safe_int(metadata.get("rounds_played")), 1)
        normalized_players: list[dict] = []
        for player in raw_players:
            stats = player.get("stats", {}) if isinstance(player.get("stats", {}), dict) else {}
            kills = self._safe_int(stats.get("kills") or player.get("kills"))
            deaths = self._safe_int(stats.get("deaths") or player.get("deaths"))
            assists = self._safe_int(stats.get("assists") or player.get("assists"))
            score = self._safe_int(stats.get("score") or player.get("score"))
            acs = self._safe_int(player.get("acs") or stats.get("acs"))
            if not acs and score:
                acs = round(score / rounds_played)
            name = str(player.get("name", "")).strip()
            tag = str(player.get("tag", "")).strip()
            riot_id = f"{name}#{tag}" if name and tag else str(player.get("display_name", "")).strip()
            normalized_players.append(
                {
                    "display_name": riot_id if riot_id else str(player.get("display_name", "")).strip() or "Jogador",
                    "riot_id": self._normalize_player_identity(riot_id),
                    "side": str(player.get("team", "") or player.get("team_id", "")).strip().lower(),
                    "acs": acs,
                    "kills": kills,
                    "deaths": deaths,
                    "assists": assists,
                }
            )
        return normalized_players

    def _extract_official_team_scores(self, official_match: dict) -> dict[str, dict]:
        teams_payload = official_match.get("teams", {})
        normalized_scores: dict[str, dict] = {}
        if isinstance(teams_payload, dict):
            iterable = teams_payload.items()
        elif isinstance(teams_payload, list):
            iterable = []
            for team in teams_payload:
                if not isinstance(team, dict):
                    continue
                side_name = str(team.get("team", "") or team.get("name", "")).strip().lower()
                if side_name:
                    iterable.append((side_name, team))
        else:
            iterable = []

        for side_name, payload in iterable:
            if not isinstance(payload, dict):
                continue
            normalized_scores[str(side_name).strip().lower()] = {
                "score": self._safe_int(payload.get("rounds_won") or payload.get("score") or payload.get("wins")),
                "won": bool(payload.get("won") or payload.get("has_won") or payload.get("winner")),
            }
        return normalized_scores

    def _resolve_official_team_mapping(self, match: dict, official_players: list[dict], source_player: str) -> dict[str, str]:
        team_names = [match["team1"], match["team2"]]
        team_rosters = {
            team_name: {self._normalize_player_identity(player_name) for player_name in self._get_team_riot_ids(team_name)}
            for team_name in team_names
        }
        side_names = [player["side"] for player in official_players if player.get("side")]
        ordered_sides = list(dict.fromkeys(side_names))
        mapping: dict[str, str] = {}
        remaining_teams = team_names[:]
        overlap_scores: dict[str, dict[str, int]] = {}
        for side_name in ordered_sides:
            side_players = {player["riot_id"] for player in official_players if player.get("side") == side_name}
            overlap_scores[side_name] = {
                team_name: len(side_players & team_rosters.get(team_name, set()))
                for team_name in team_names
            }

        for team_name in team_names:
            candidate_side = ""
            candidate_score = -1
            for side_name in ordered_sides:
                if side_name in mapping:
                    continue
                score = overlap_scores.get(side_name, {}).get(team_name, 0)
                if score > candidate_score:
                    candidate_side = side_name
                    candidate_score = score
            if candidate_side and candidate_score > 0:
                mapping[candidate_side] = team_name
                if team_name in remaining_teams:
                    remaining_teams.remove(team_name)

        source_identity = self._normalize_player_identity(source_player)
        if source_identity:
            for player in official_players:
                if player.get("riot_id") == source_identity and player.get("side") in ordered_sides:
                    source_side = player["side"]
                    if source_side not in mapping:
                        for team_name in team_names:
                            if source_identity in team_rosters.get(team_name, set()):
                                mapping[source_side] = team_name
                                if team_name in remaining_teams:
                                    remaining_teams.remove(team_name)
                                break

        for side_name in ordered_sides:
            if side_name not in mapping and remaining_teams:
                mapping[side_name] = remaining_teams.pop(0)
        return mapping

    def _build_official_match_payload(self, match: dict, official_match: dict, source_player: str, region: str) -> dict:
        metadata = official_match.get("metadata", {}) if isinstance(official_match.get("metadata", {}), dict) else {}
        official_players = self._extract_official_players(official_match)
        score_lookup = self._extract_official_team_scores(official_match)
        side_mapping = self._resolve_official_team_mapping(match, official_players, source_player)
        team_payloads: list[dict] = []
        mvp_player: dict | None = None

        for official_side, team_name in side_mapping.items():
            team_players = [player for player in official_players if player.get("side") == official_side]
            team_players.sort(key=lambda player: (player.get("acs", 0), player.get("kills", 0)), reverse=True)
            team_roster = {self._normalize_player_identity(player_name) for player_name in self._get_team_riot_ids(team_name)}
            matched_player_count = len({player.get("riot_id", "") for player in team_players} & team_roster)
            score_payload = score_lookup.get(official_side, {})
            team_payload = {
                "name": team_name,
                "side": official_side,
                "score": score_payload.get("score", 0),
                "won": bool(score_payload.get("won")),
                "matched_player_count": matched_player_count,
                "players": team_players,
            }
            team_payloads.append(team_payload)
            top_player = team_players[0] if team_players else None
            if top_player and (mvp_player is None or (top_player.get("acs", 0), top_player.get("kills", 0)) > (mvp_player.get("acs", 0), mvp_player.get("kills", 0))):
                mvp_player = top_player

        if len(team_payloads) < 2:
            for team_name in [match["team1"], match["team2"]]:
                if team_name not in {payload["name"] for payload in team_payloads}:
                    team_payloads.append({"name": team_name, "side": "", "score": 0, "won": False, "matched_player_count": 0, "players": []})

        team_payloads.sort(key=lambda payload: 0 if payload.get("name") == match["team1"] else 1)
        winner_payload = next((payload for payload in team_payloads if payload.get("won")), None)
        if not winner_payload:
            winner_payload = max(team_payloads, key=lambda payload: payload.get("score", 0), default=None)
        winner_name = winner_payload.get("name", "") if winner_payload else ""

        explicit_mvp = official_match.get("mvp")
        if isinstance(explicit_mvp, dict):
            explicit_name = str(explicit_mvp.get("name", "")).strip()
            explicit_tag = str(explicit_mvp.get("tag", "")).strip()
            if explicit_name:
                explicit_display = f"{explicit_name}#{explicit_tag}" if explicit_tag else explicit_name
                mvp_player = {"display_name": explicit_display, "acs": self._safe_int(explicit_mvp.get("acs")), "kills": self._safe_int(explicit_mvp.get("kills")), "deaths": self._safe_int(explicit_mvp.get("deaths")), "assists": self._safe_int(explicit_mvp.get("assists"))}

        map_name = str(metadata.get("map") or official_match.get("map") or "").strip()
        started_at = str(metadata.get("game_start_patched") or metadata.get("started_at") or official_match.get("started_at") or "").strip()
        result_line = ""
        if len(team_payloads) >= 2:
            result_line = f"{team_payloads[0]['name']} {team_payloads[0].get('score', 0)} x {team_payloads[1].get('score', 0)} {team_payloads[1]['name']}"

        map_entry = {
            "map_name": map_name,
            "started_at": started_at,
            "winner": winner_name,
            "result_line": result_line,
            "mvp": mvp_player.get("display_name", "") if isinstance(mvp_player, dict) else "",
            "teams": [dict(payload) for payload in team_payloads],
        }

        return {
            "provider": "henrikdev",
            "source_player": source_player,
            "region": region,
            "metadata": {
                "map_name": map_name,
                "started_at": started_at,
                "mode": str(metadata.get("mode") or official_match.get("mode") or "Custom Game").strip(),
                "cluster": str(metadata.get("cluster") or official_match.get("cluster") or "").strip(),
                "mvp": mvp_player.get("display_name", "") if isinstance(mvp_player, dict) else "",
                "result_line": result_line,
            },
            "winner": winner_name,
            "teams": team_payloads,
            "maps": [map_entry],
            "mvp": mvp_player or {},
        }

    def _official_payload_matches_teams(self, official_payload: dict) -> bool:
        teams_payload = official_payload.get("teams", []) if isinstance(official_payload, dict) else []
        matched_counts = [self._safe_int(team.get("matched_player_count", 0)) for team in teams_payload if isinstance(team, dict)]
        return len(matched_counts) >= 2 and matched_counts[0] > 0 and matched_counts[1] > 0

    def _find_latest_captain_match_payload(self, match: dict, api_keys: list[str]) -> tuple[dict | None, str]:
        candidate_players: list[str] = []
        for team_name in (match["team1"], match["team2"]):
            captain_riot_id = self._get_team_captain_riot_id(team_name)
            if captain_riot_id and captain_riot_id not in candidate_players:
                candidate_players.append(captain_riot_id)

        if not candidate_players:
            return None, "Defina o capitao como primeiro jogador de cada time usando o formato Nick#TAG para buscar dados oficiais."

        fallback_payload: dict | None = None
        searched_players: list[str] = []
        for riot_id in candidate_players:
            parsed_riot_id = parse_riot_id(riot_id)
            if not parsed_riot_id:
                continue
            searched_players.append(riot_id)
            for region in ("br", "latam", "na", "eu", "ap", "kr"):
                try:
                    official_match = fetch_latest_match(region, parsed_riot_id[0], parsed_riot_id[1], api_key=api_keys, timeout=6.0)
                except PermissionError:
                    raise
                except HenrikRateLimitError:
                    raise
                except Exception:
                    continue
                if not official_match:
                    continue

                payload = self._build_official_match_payload(match, official_match, riot_id, region)
                if self._official_payload_matches_teams(payload):
                    return payload, f"Ultima partida oficial localizada via capitao {riot_id} ({region.upper()})."
                if fallback_payload is None:
                    fallback_payload = payload
                break

        if fallback_payload is not None:
            return fallback_payload, "Uma ultima partida foi localizada por capitao, mas o cruzamento dos dois times nao ficou totalmente confirmado."
        if searched_players:
            return None, "Nenhuma partida recente foi localizada para os capitaes cadastrados."
        return None, "Nenhum capitao com Riot ID valido foi encontrado para esta partida."

    def _apply_official_match_payload(self, match_id: str, match: dict, official_payload: dict) -> None:
        match_results = self.state.setdefault("match_results", {})
        existing_result = dict(match_results.get(match_id, {}))
        teams_payload = official_payload.get("teams", []) if isinstance(official_payload, dict) else []
        team_lookup = {payload.get("name", ""): payload for payload in teams_payload if isinstance(payload, dict)}
        team_one_payload = team_lookup.get(match["team1"], {})
        team_two_payload = team_lookup.get(match["team2"], {})
        winner_name = str(official_payload.get("winner", "")).strip()
        winner_slot = winner_slot_from_name(match, winner_name)
        mvp_payload = official_payload.get("mvp", {}) if isinstance(official_payload.get("mvp", {}), dict) else {}
        official_mvp = str(mvp_payload.get("display_name", "")).strip()
        official_kd = ""
        if official_mvp:
            official_kd = f"{self._safe_int(mvp_payload.get('kills'))}/{self._safe_int(mvp_payload.get('deaths'))}/{self._safe_int(mvp_payload.get('assists'))}"

        metadata = official_payload.get("metadata", {}) if isinstance(official_payload.get("metadata", {}), dict) else {}
        result_line = str(metadata.get("result_line", "")).strip()

        existing_result.update(
            {
                "winner_slot": winner_slot or existing_result.get("winner_slot", ""),
                "team1_score": str(team_one_payload.get("score", "") or existing_result.get("team1_score", "")),
                "team2_score": str(team_two_payload.get("score", "") or existing_result.get("team2_score", "")),
                "map_name": str(metadata.get("map_name", "") or existing_result.get("map_name", "")),
                "official_result": result_line or existing_result.get("official_result", ""),
                "official_acs": f"MVP ACS {self._safe_int(mvp_payload.get('acs'))}" if self._safe_int(mvp_payload.get("acs")) else existing_result.get("official_acs", ""),
                "official_kd": official_kd or existing_result.get("official_kd", ""),
                "official_mvp": official_mvp or existing_result.get("official_mvp", ""),
                "official_data": official_payload,
            }
        )
        match_results[match_id] = existing_result

    def _set_official_validation_state(self, active: bool) -> None:
        self.validation_in_progress = active
        if hasattr(self, "validate_official_button"):
            self.validate_official_button.configure(state="disabled" if active else "normal")
            self.validate_official_button.configure(text="Buscando..." if active else "Buscar ultima dos capitaes")
        if hasattr(self, "official_lookup_status_var"):
            self.official_lookup_status_var.set("Consultando a API oficial..." if active else self.official_lookup_status_var.get())
        try:
            self.configure(cursor="watch" if active else "")
        except tk.TclError:
            pass

    def _run_official_validation_worker(self, match_id: str, match_snapshot: dict, api_keys: list[str], result_queue: queue.Queue) -> None:
        try:
            official_payload, status_message = self._find_latest_captain_match_payload(match_snapshot, api_keys)
        except PermissionError:
            result_queue.put((None, "permission-error", True))
            return
        except HenrikRateLimitError as exc:
            result_queue.put((None, str(exc), False))
            return
        except Exception as exc:
            result_queue.put((None, str(exc), False))
            return

        result_queue.put((official_payload, status_message, False))

    def _poll_official_validation_result(self, match_id: str, match_snapshot: dict, result_queue: queue.Queue) -> None:
        try:
            official_payload, status_message, invalid_key = result_queue.get_nowait()
        except queue.Empty:
            if self.validation_in_progress:
                self.after(120, lambda: self._poll_official_validation_result(match_id, match_snapshot, result_queue))
            return
        self._finish_official_validation(match_id, match_snapshot, official_payload, status_message, invalid_key)

    def _finish_official_validation(self, match_id: str, match_snapshot: dict, official_payload: dict | None, status_message: str, invalid_key: bool) -> None:
        self._set_official_validation_state(False)

        if invalid_key:
            self._store_henrik_api_keys([])
            self._save_state()
            messagebox.showerror("Validacao oficial", "As chaves da API HenrikDev foram rejeitadas. Abra novamente a validacao e informe uma chave valida.")
            return

        if not official_payload:
            if hasattr(self, "official_lookup_status_var"):
                self.official_lookup_status_var.set(status_message or "Nenhum dado oficial foi localizado.")
            self._set_app_feedback(status_message or "Nenhum dado oficial foi localizado.", tone="info", persist_ms=7000)
            return

        current_match = self._get_match_by_id(match_id) or match_snapshot
        self._apply_official_match_payload(match_id, current_match, official_payload)
        self._save_state()
        self._refresh_everything(preserve_selected_match=True)
        self._load_match_details(match_id)
        if hasattr(self, "official_lookup_status_var"):
            self.official_lookup_status_var.set(status_message or "Dados oficiais aplicados com sucesso.")
        self._set_app_feedback(status_message or "Dados oficiais aplicados com sucesso.", tone="success", persist_ms=7000)

    def _draw_match_card(self, match: dict, position: tuple[int, int], card_size: tuple[int, int], scale: float) -> None:
        x_pos, y_pos = position
        card_width, card_height = card_size
        selected_match_id = self.state.get("selected_match_id", "")
        is_selected = match["id"] == selected_match_id
        border_color = "#f1f1f1" if is_selected else "#343840"
        row_height = (card_height - max(24 * scale, 20)) / 2
        tag = f"bracket-match:{match['id']}"
        scheduled_date = match.get("scheduled_date", "").strip() or "Sem data"
        top_bar_height = max(22 * scale, 20)
        info_column_width = max(58 * scale, 52)
        logo_size = max(26, int(30 * scale))
        left_padding = max(10, int(14 * scale))
        team_font_size = max(10, int(16 * scale))
        meta_font_size = max(8, int(9 * scale))
        date_font_size = max(8, int(9 * scale))
        score_font_size = max(9, int(14 * scale))
        body_top = y_pos + top_bar_height
        first_row_center = body_top + (row_height / 2)
        second_row_center = body_top + row_height + (row_height / 2)
        divider_x = x_pos + card_width - info_column_width
        text_width = max(divider_x - x_pos - (left_padding * 2) - logo_size - 18, 72)

        items: list[int] = [
            self.bracket_canvas.create_rectangle(
                x_pos,
                y_pos,
                x_pos + card_width,
                y_pos + card_height,
                outline=border_color,
                width=2 if is_selected else 1,
                fill="#17181c",
                tags=(tag,),
            ),
            self.bracket_canvas.create_rectangle(
                x_pos,
                y_pos,
                x_pos + card_width,
                y_pos + top_bar_height,
                outline="",
                fill="#1a1c20",
                tags=(tag,),
            ),
            self.bracket_canvas.create_rectangle(
                divider_x,
                body_top,
                x_pos + card_width,
                y_pos + card_height,
                outline="",
                fill="#14161a",
                tags=(tag,),
            ),
            self.bracket_canvas.create_line(
                x_pos,
                body_top + row_height,
                x_pos + card_width,
                body_top + row_height,
                fill="#2a2d33",
                width=max(1, int(scale)),
                tags=(tag,),
            ),
            self.bracket_canvas.create_line(
                divider_x,
                body_top,
                divider_x,
                y_pos + card_height,
                fill="#2a2d33",
                width=max(1, int(scale)),
                tags=(tag,),
            ),
        ]

        top_left_item = self.bracket_canvas.create_text(
            x_pos + left_padding,
            y_pos + (top_bar_height / 2),
            text=f"{match['id']} {match['best_of']}",
            fill="#f2f2f2",
            anchor="w",
            font=(self.title_font_family, meta_font_size, "bold"),
            tags=(tag,),
        )
        date_item = self.bracket_canvas.create_text(
            x_pos + card_width - left_padding,
            y_pos + (top_bar_height / 2),
            text=scheduled_date,
            fill="#f0f0f0" if scheduled_date != "Sem data" else "#b2b7bf",
            anchor="e",
            font=(self.title_font_family, date_font_size, "bold"),
            tags=(tag,),
        )
        items.extend([top_left_item, date_item])

        team_text_items: list[int] = []
        score_text_items: list[int] = []

        for row_index, team_key in enumerate(("team1", "team2")):
            team_name = (match.get(team_key, "") or "A definir").upper()
            is_winner = match["winner"] == match.get(team_key, "")
            row_center = first_row_center if row_index == 0 else second_row_center
            team_text_item = self.bracket_canvas.create_text(
                x_pos + left_padding,
                row_center,
                text=team_name,
                fill="#f3f3f3" if is_winner else "#e4e7eb",
                anchor="w",
                width=text_width,
                font=(self.title_font_family, team_font_size, "bold"),
                tags=(tag,),
            )
            score_text_item = self.bracket_canvas.create_text(
                divider_x + (info_column_width / 2),
                row_center,
                text=(match.get(f"team{row_index + 1}_score", "") or ""),
                fill="#f3f3f3",
                anchor="center",
                font=(self.title_font_family, score_font_size, "bold"),
                tags=(tag,),
            )
            team_text_items.append(team_text_item)
            score_text_items.append(score_text_item)
            items.extend([team_text_item, score_text_item])

        for team_index, team_key in enumerate(("team1", "team2")):
            profile = self._get_team_profile_by_name(match.get(team_key, ""))
            row_center = first_row_center if team_index == 0 else second_row_center
            logo_x = x_pos + left_padding + (logo_size / 2)
            if profile:
                logo_image = self._load_logo_image(profile.get("logo_path", ""), max_size=logo_size)
            else:
                logo_image = None
            if logo_image:
                self.bracket_logo_refs.append(logo_image)
                items.append(self.bracket_canvas.create_image(logo_x, row_center, image=logo_image, tags=(tag,)))
            else:
                items.append(
                    self.bracket_canvas.create_rectangle(
                        x_pos + left_padding,
                        row_center - (logo_size / 2),
                        x_pos + left_padding + logo_size,
                        row_center + (logo_size / 2),
                        outline="#353941",
                        fill="#121418",
                        tags=(tag,),
                    )
                )
            self.bracket_canvas.create_text(
                x_pos + left_padding + (logo_size / 2),
                row_center,
                text="",
                fill="#f3f3f3",
                anchor="center",
                tags=(tag,),
            )
            self.bracket_canvas.coords(team_text_items[team_index], x_pos + left_padding + logo_size + 18, row_center)

        self.bracket_card_items[match["id"]] = items
        self.bracket_canvas.tag_bind(tag, "<Button-1>", lambda _event, match_id=match["id"]: self._select_bracket_match(match_id))
        self.bracket_canvas.tag_bind(tag, "<Double-1>", lambda _event, match_id=match["id"]: self._open_bracket_match(match_id))

    def _draw_match_connectors(self, match: dict, position: tuple[int, int], positions: dict, card_size: tuple[int, int], scale: float) -> None:
        x_pos, y_pos = position
        card_width, _card_height = card_size
        top_bar_height = max(22 * scale, 20)
        row_height = (card_size[1] - top_bar_height) / 2
        slot_targets = {
            "slot1": y_pos + top_bar_height + (row_height / 2),
            "slot2": y_pos + top_bar_height + row_height + (row_height / 2),
        }
        for slot_name in ("slot1", "slot2"):
            slot = match[slot_name]
            if slot["kind"] == "team":
                continue
            source_match_id = slot["match"]
            if source_match_id.startswith("UB") and match["id"].startswith("LB"):
                continue
            source_position = positions.get(slot["match"])
            if not source_position:
                continue
            source_x, source_y = source_position
            source_right = source_x + card_width
            source_mid_y = source_y + top_bar_height + row_height
            target_left = x_pos
            target_y = slot_targets[slot_name]
            elbow_x = source_right + max(24 * scale, 20)
            self.bracket_canvas.create_line(
                source_right,
                source_mid_y,
                elbow_x,
                source_mid_y,
                elbow_x,
                target_y,
                target_left,
                target_y,
                fill="#e8eaed",
                width=max(1, int(2 * scale)),
            )

    def _select_bracket_match(self, match_id: str) -> None:
        self.state["selected_match_id"] = match_id
        self._save_state()
        self._refresh_bracket_view()

    def _open_bracket_match(self, match_id: str) -> None:
        self.state["selected_match_id"] = match_id
        self._save_state()
        self._refresh_match_selector(preserve_selected_match=True)
        self._open_admin_matches_panel()

    def _open_admin_matches_panel(self) -> None:
        self._select_tab(0)
        if self.admin_authenticated:
            self.admin_notebook.select(self.admin_matches_tab)
        else:
            self.admin_login_feedback_var.set("Entre para administrar as partidas.")

    def _refresh_match_selector(self, preserve_selected_match: bool = False) -> None:
        selected_match_id = self.state.get("selected_match_id", "") if preserve_selected_match else ""
        self.match_options = {}
        option_labels: list[str] = []

        self.match_listbox.delete(0, "end")
        for match in self.resolved_matches:
            label = self._get_admin_match_option_label(match)
            option_labels.append(label)
            self.match_options[label] = match["id"]
            self.match_listbox.insert("end", label)

        self.match_combo["values"] = option_labels
        if option_labels:
            desired_match_id = selected_match_id or self.resolved_matches[0]["id"]
            desired_label = next(
                (label for label, match_id in self.match_options.items() if match_id == desired_match_id),
                option_labels[0],
            )
            self.match_selection_var.set(desired_label)
            self._set_listbox_selection(desired_label)
            self._load_match_details(self.match_options[desired_label])
        else:
            self.match_selection_var.set("")
            self._reset_match_form()

    def _save_state(self) -> None:
        self.storage.save(self.state)

    def _save_cards_pool(self) -> None:
        self.state["cards_pool"] = clean_lines(self.cards_text.get("1.0", "end"))
        self._save_state()
        self._set_app_feedback("Pool de cartas salvo com sucesso.", tone="success")

    def _draw_next_card(self) -> None:
        cards_pool = clean_lines(self.cards_text.get("1.0", "end"))
        if not cards_pool:
            messagebox.showwarning("Cartas", "Adicione ao menos uma carta para sortear.")
            return

        self.state["cards_pool"] = cards_pool
        drawn_cards = self.state.setdefault("drawn_cards", [])
        remaining_cards = [card for card in cards_pool if card not in drawn_cards]
        if not remaining_cards:
            self._set_app_feedback("Todas as cartas ja foram sorteadas. Use o reset para recomecar.", tone="info")
            return

        next_card = random.choice(remaining_cards)
        drawn_cards.append(next_card)
        self._save_state()
        self._refresh_cards_panel()

    def _reset_card_draw(self) -> None:
        self.state["drawn_cards"] = []
        self._save_state()
        self._refresh_cards_panel()

    def _save_players_pool(self) -> None:
        self.state["players_pool"] = clean_lines(self.players_text.get("1.0", "end"))
        self.state["team_count"] = int(self.team_count_var.get())
        self._save_state()
        self._set_app_feedback("Lista de jogadores salva.", tone="success")

    def _draw_teams(self) -> None:
        players = clean_lines(self.players_text.get("1.0", "end"))
        team_count = int(self.team_count_var.get())
        if len(players) < team_count:
            messagebox.showwarning("Times", "A quantidade de jogadores precisa ser maior ou igual ao numero de times.")
            return

        shuffled_players = players[:]
        random.shuffle(shuffled_players)
        generated_teams = [{"name": f"Time {index + 1}", "players": []} for index in range(team_count)]

        for index, player in enumerate(shuffled_players):
            generated_teams[index % team_count]["players"].append(player)

        self.state["players_pool"] = players
        self.state["team_count"] = team_count
        self.state["generated_teams"] = generated_teams
        self._save_state()
        self._refresh_teams_tree()

    def _use_generated_teams(self) -> None:
        generated_teams = self.state.get("generated_teams", [])
        if not generated_teams:
            messagebox.showwarning("Chave", "Nenhum time sorteado disponivel.")
            return

        team_names = [team["name"] for team in generated_teams]
        bracket_size = infer_bracket_size(team_names)
        if bracket_size is None:
            messagebox.showwarning("Chave", "A chave double elimination atual suporta apenas 4 ou 8 times.")
            return

        self.state["registered_teams"] = team_names
        self.state["bracket_size"] = bracket_size
        self.state["match_results"] = {}
        self.state["selected_match_id"] = ""
        profiles = self._get_team_profiles()
        for index, team in enumerate(generated_teams[:8]):
            profiles[index] = {
                "slot": index,
                "name": team.get("name", ""),
                "logo_path": "",
                "coach": "",
                "players": (team.get("players", []) + ["", "", "", "", ""])[:5],
            }
        self.state["team_profiles"] = profiles
        self._save_state()
        self._refresh_everything()
        self._populate_admin_bracket_from_profiles()
        self._select_tab(3)

    def _clear_generated_teams(self) -> None:
        self.state["generated_teams"] = []
        self._save_state()
        self._refresh_teams_tree()

    def _save_bracket_teams(self) -> None:
        team_names = clean_lines(self.admin_bracket_teams_text.get("1.0", "end"))
        bracket_size = infer_bracket_size(team_names)
        if bracket_size is None:
            messagebox.showwarning("Chave", "Digite exatamente 4 ou 8 times.")
            return

        self.state["registered_teams"] = team_names
        self.state["bracket_size"] = bracket_size
        self._save_state()
        self._refresh_everything(preserve_selected_match=True)
        self._set_app_feedback("Times da chave salvos.", tone="success")

    def _build_bracket(self) -> None:
        team_names = clean_lines(self.admin_bracket_teams_text.get("1.0", "end"))
        bracket_size = infer_bracket_size(team_names)
        if bracket_size is None:
            messagebox.showwarning("Chave", "Digite exatamente 4 ou 8 times para montar a chave.")
            return

        current_teams = self.state.get("registered_teams", [])
        if current_teams != team_names:
            self.state["match_results"] = {}

        self.state["registered_teams"] = team_names
        self.state["bracket_size"] = bracket_size
        self.state["selected_match_id"] = ""
        self._save_state()
        self._refresh_everything()

    def _open_selected_match_from_bracket(self) -> None:
        match_id = self.state.get("selected_match_id", "")
        if not match_id:
            self._set_app_feedback("Selecione uma partida na chave antes de abrir os detalhes.", tone="warning")
            return

        self.state["selected_match_id"] = match_id
        self._save_state()
        self._refresh_match_selector(preserve_selected_match=True)
        self._open_admin_matches_panel()

    def _load_selected_match(self, _event=None) -> None:
        label = self.match_selection_var.get()
        match_id = self.match_options.get(label)
        if match_id:
            self._set_listbox_selection(label)
            self._load_match_details(match_id)

    def _load_selected_match_from_listbox(self, _event=None) -> None:
        selection = self.match_listbox.curselection()
        if not selection:
            return

        label = self.match_listbox.get(selection[0])
        self.match_selection_var.set(label)
        match_id = self.match_options.get(label)
        if match_id:
            self._load_match_details(match_id)

    def _load_match_details(self, match_id: str) -> None:
        match = self._get_match_by_id(match_id)
        if not match:
            self._reset_match_form()
            return

        self.state["selected_match_id"] = match_id
        self._save_state()

        self.selected_match_title.configure(text=f"{match['id']} - {match['title']} ({match['best_of']})")
        self.match_team1_var.set(match["team1"])
        self.match_team2_var.set(match["team2"])
        team_one_captain = self._get_team_captain_riot_id(match["team1"])
        team_two_captain = self._get_team_captain_riot_id(match["team2"])
        self.match_team1_captain_var.set(f"Capitao: {team_one_captain or '-'}")
        self.match_team2_captain_var.set(f"Capitao: {team_two_captain or '-'}")
        status_label, status_bg, status_fg = self._get_match_admin_status(match)
        self.match_status_badge.configure(text=status_label, bg=status_bg, fg=status_fg)
        target_wins = self._get_series_target_wins(match.get("best_of", "MD1"))
        current_team1_score = self._safe_int(match.get("team1_score", 0))
        current_team2_score = self._safe_int(match.get("team2_score", 0))
        self.series_guidance_var.set(
            f"{match.get('best_of', 'MD1')} | primeiro a {target_wins} mapa(s) | parcial atual {current_team1_score} x {current_team2_score}"
        )
        winner_values = [team for team in [match["team1"], match["team2"]] if team != "A definir"]
        self.match_winner_combo["values"] = winner_values
        self.match_winner_var.set(match["winner"] if match["winner"] in winner_values else "")
        self.team1_score_var.set(match.get("team1_score", ""))
        self.team2_score_var.set(match.get("team2_score", ""))
        self.map_name_var.set(match.get("map_name", ""))
        self.official_result_var.set(match.get("official_result", ""))
        self.official_acs_var.set(match.get("official_acs", ""))
        self.official_kd_var.set(match.get("official_kd", ""))
        self.official_mvp_var.set(match.get("official_mvp", ""))
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", match.get("notes", ""))
        official_metadata = match.get("official_data", {}) if isinstance(match.get("official_data", {}), dict) else {}
        source_player = str(official_metadata.get("source_player", "")).strip()
        suggestion = self._build_official_suggestion(match)
        if suggestion.get("has_data"):
            winner_text = suggestion.get("winner", "-") or "-"
            score_one = suggestion.get("team1_score", "-") or "-"
            score_two = suggestion.get("team2_score", "-") or "-"
            map_text = suggestion.get("map_name", "-") or "-"
            self.official_suggestion_var.set(f"Sugestao: {winner_text} | {score_one} x {score_two} | mapa {map_text}")
        else:
            self.official_suggestion_var.set("Sem sugestao oficial carregada.")
        if source_player:
            self.official_lookup_status_var.set(f"Ultima sincronizacao oficial via capitao {source_player}.")
        else:
            self.official_lookup_status_var.set("Pronto para buscar a ultima partida dos capitaes.")

    def _save_selected_match_result(self) -> None:
        match_id = self.state.get("selected_match_id", "")
        match = self._get_match_by_id(match_id)
        if not match:
            messagebox.showwarning("Partidas", "Selecione uma partida antes de salvar.")
            return

        if not match_can_receive_result(match):
            messagebox.showwarning("Partidas", "Essa partida ainda nao tem os dois times definidos.")
            return

        winner_name = self.match_winner_var.get().strip()
        winner_slot = winner_slot_from_name(match, winner_name)
        if winner_name and winner_slot is None:
            messagebox.showwarning("Partidas", "O vencedor precisa ser um dos times da partida.")
            return

        self.state.setdefault("match_results", {})[match_id] = {
            "winner_slot": winner_slot or "",
            "team1_score": self.team1_score_var.get().strip(),
            "team2_score": self.team2_score_var.get().strip(),
            "map_name": self.map_name_var.get().strip(),
            "official_result": self.official_result_var.get().strip(),
            "official_acs": self.official_acs_var.get().strip(),
            "official_kd": self.official_kd_var.get().strip(),
            "official_mvp": self.official_mvp_var.get().strip(),
            "official_data": self.state.get("match_results", {}).get(match_id, {}).get("official_data", {}),
            "notes": self.notes_text.get("1.0", "end").strip(),
        }
        self._save_state()
        self._refresh_everything(preserve_selected_match=True)
        self._set_app_feedback("Resultado salvo.", tone="success")

    def _clear_selected_match_result(self) -> None:
        match_id = self.state.get("selected_match_id", "")
        if not match_id:
            return

        self.state.setdefault("match_results", {}).pop(match_id, None)
        self._save_state()
        self._refresh_everything(preserve_selected_match=True)

    def _validate_official_data(self) -> None:
        if self.validation_in_progress:
            return

        match_id = self.state.get("selected_match_id", "")
        match = self._get_match_by_id(match_id)
        if not match:
            messagebox.showwarning("Validacao oficial", "Selecione uma partida antes de validar.")
            return
        if not match_can_receive_result(match):
            messagebox.showwarning("Validacao oficial", "A validacao oficial so funciona quando os dois times ja estao definidos.")
            return

        api_keys = self._ensure_henrik_api_keys()
        if not api_keys:
            self._set_app_feedback(
                "Sem chave de API nao da para consultar o historico oficial. A API HenrikDev exige autenticacao para endpoints de partidas.",
                tone="warning",
                persist_ms=7000,
            )
            return

        captain_one = self._get_team_captain_riot_id(match["team1"])
        captain_two = self._get_team_captain_riot_id(match["team2"])
        if not captain_one or not captain_two:
            messagebox.showwarning(
                "Validacao oficial",
                "Os dois times precisam ter o capitao definido como primeiro jogador no formato Nick#TAG.",
            )
            return

        self._set_official_validation_state(True)
        result_queue: queue.Queue = queue.Queue()
        worker = threading.Thread(
            target=self._run_official_validation_worker,
            args=(match_id, dict(match), api_keys, result_queue),
            daemon=True,
        )
        worker.start()
        self.after(120, lambda: self._poll_official_validation_result(match_id, dict(match), result_queue))

    def _reset_match_form(self) -> None:
        self.selected_match_title.configure(text="Nenhuma partida selecionada.")
        self.match_team1_var.set("-")
        self.match_team2_var.set("-")
        self.match_team1_captain_var.set("Capitao: -")
        self.match_team2_captain_var.set("Capitao: -")
        self.match_status_badge.configure(text="AGUARDANDO", bg="#262a30", fg="#f1f3f5")
        self.official_lookup_status_var.set("Validacao oficial pronta para buscar a ultima partida dos capitaes.")
        self.series_guidance_var.set("Serie pronta para preenchimento guiado.")
        self.official_suggestion_var.set("Sem sugestao oficial carregada.")
        self.match_winner_var.set("")
        self.match_winner_combo["values"] = []
        self.team1_score_var.set("")
        self.team2_score_var.set("")
        self.map_name_var.set("")
        self.official_result_var.set("")
        self.official_acs_var.set("")
        self.official_kd_var.set("")
        self.official_mvp_var.set("")
        if hasattr(self, "henrik_api_key_var"):
            self.henrik_api_key_var.set(self._get_henrik_api_key_value())
        self.notes_text.delete("1.0", "end")

    def _get_match_by_id(self, match_id: str) -> dict | None:
        return next((match for match in self.resolved_matches if match["id"] == match_id), None)

    def _set_listbox_selection(self, label: str) -> None:
        self.match_listbox.selection_clear(0, "end")
        values = self.match_listbox.get(0, "end")
        for index, current_label in enumerate(values):
            if current_label == label:
                self.match_listbox.selection_set(index)
                self.match_listbox.see(index)
                break

    def _handle_tab_change(self, _event=None) -> None:
        self.current_tab_index = self.notebook.index(self.notebook.select())
        self._set_active_content_nav(self.current_tab_index)
        self._update_back_button_state()
        if self.current_tab_index == 4:
            self._refresh_map_views()

    def _handle_admin_panel_tab_change(self, _event=None) -> None:
        try:
            if str(self.admin_notebook.select()) == str(self.admin_maps_tab):
                self._refresh_map_views()
            elif str(self.admin_notebook.select()) == str(self.admin_portal_tab):
                self._refresh_portal_admin_dashboard()
            elif str(self.admin_notebook.select()) == str(self.admin_users_tab):
                self._refresh_portal_users()
        except tk.TclError:
            return

    def _go_back(self) -> None:
        self._show_home_screen()

    def _select_tab(self, index: int) -> None:
        if index == 0:
            self._open_panel_window()
            return
        self._show_content_view()
        self.notebook.select(self.tab_frames[index])
        self.current_tab_index = index
        self._set_active_content_nav(index)
        self._update_back_button_state()

    def _update_back_button_state(self) -> None:
        if self.home_is_visible:
            self.back_button.configure(state="disabled", bg="#303030", fg="#9f9f9f", cursor="arrow")
        else:
            self.back_button.configure(state="normal", bg="#111111", fg="#f2f2f2", cursor="hand2")
