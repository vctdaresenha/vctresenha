# VCT da Resenha

Aplicativo desktop para organizar o campeonato VCT da Resenha.

Agora o projeto tambem inclui um portal web para os capitaes fazerem login com Discord, cadastrar os times e enviar alteracoes para analise da producao. O aplicativo desktop continua sendo o painel administrativo e sincroniza os times aprovados pelo backend.

Tambem existe um runner dedicado para um bot do Discord, usando a mesma configuracao central do app e do portal para facilitar o deploy na VPS.

Para producao, a melhor opcao e usar GitHub Actions para disparar um script de deploy na VPS a cada `push` na branch principal.

## O que ja esta pronto

- Sorteio de cartas com historico e reset.
- Sorteio de times a partir de uma lista de jogadores.
- Chave double elimination para 4 ou 8 times.
- Regras de series configuradas assim:
  - Partidas padrao: MD1
  - Final da Upper Bracket: MD3
  - Final da Lower Bracket: MD3
  - Grand Final: MD5
- Aba de detalhes da partida com campos separados para:
  - resultado oficial
  - ACS
  - K/D
  - mapa
  - vencedor
  - MVP
- Persistencia local estavel em `%LOCALAPPDATA%\VCT da Resenha\data\championship_state.json`.
- Se existir um estado antigo em `data/championship_state.json`, ele e migrado automaticamente.
- Validacao de jogadores com cache local para evitar consultar a API novamente para IDs ja confirmados.
- Suporte a varias chaves da API HenrikDev, com fallback automatico quando uma chave atinge o limite de requisicoes.
- Portal web em FastAPI com login via Discord, captcha Turnstile, cadastro de time e fila de aprovacao.
- Sincronizacao do painel desktop com a fila do portal para aprovar, recusar e importar times aprovados.

## Como executar

Precisa ter Python 3.11+ instalado no Windows.

```powershell
python main.py
```

Para subir o portal web localmente:

```powershell
python portal_main.py
```

O portal abre por padrao em `http://127.0.0.1:8000`.

Para subir o bot do Discord localmente:

```powershell
python discord_bot_main.py
```

O bot so conecta se `discord_bot.enabled` estiver como `true` e se `discord_bot.token` estiver preenchido em `config/app_settings.json`.

## Deploy automatico

O repositorio inclui:

- `scripts/deploy_vps.sh`: atualiza o clone Git na VPS, instala dependencias na `.venv` e reinicia portal e bot
- `.github/workflows/deploy-vps.yml`: workflow que conecta por SSH na VPS e executa o script de deploy a cada `push` na branch `main`

Para usar esse fluxo, voce precisa:

1. deixar o projeto versionado em um repositorio GitHub
2. manter o clone da VPS em `/opt/vctresenha`
3. configurar no GitHub os secrets `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY` e `VPS_PORT`

Os passos completos de configuracao estao em `DEPLOY_SHARDCLOUD_VPS.md`.

## Configuracao

O arquivo `config/app_settings.json` centraliza:

- credenciais do painel admin desktop
- token e presenca do bot do Discord
- URL base e token admin do portal
- chaves do Discord OAuth
- chaves do Cloudflare Turnstile
- informacoes exibidas no rodape do site

Antes de publicar, altere principalmente:

- `admin.password`
- `discord_bot.enabled`
- `discord_bot.token`
- `portal.admin_token`
- `portal.session_secret`
- `portal.discord_client_id`
- `portal.discord_client_secret`
- `portal.discord_redirect_uri`
- `portal.turnstile_site_key`
- `portal.turnstile_secret_key`

Sem as credenciais reais do Discord e do Turnstile, o backend sobe normalmente, mas o login social e o captcha nao ficam operacionais para uso publico.

## Como gerar o .exe

Instale o PyInstaller no ambiente Python usado para rodar o app:

```powershell
python -m pip install pyinstaller
```

Depois gere o executavel:

```powershell
python -m PyInstaller --noconfirm --onefile --windowed --add-data "assets;assets" --name "VCT da Resenha" main.py
```

O executavel sera criado em `dist/VCT da Resenha.exe`.

## API HenrikDev

Na aba `Partidas`, o campo da API HenrikDev agora aceita uma ou mais chaves separadas por virgula, ponto e virgula ou quebra de linha.

Quando uma chave atingir o limite de requisicoes, o app tenta automaticamente a proxima chave configurada.

No fluxo novo de cadastro, a validacao individual dos jogadores acontece no momento em que a producao aprova a submissao do time no painel do aplicativo.

## Proximo passo tecnico

A validacao oficial dos dados da partida esta preparada na interface, mas a fonte de dados ainda precisa ser conectada. O ponto de extensao mais simples e adicionar um servico para consultar a API oficial e preencher automaticamente os campos da aba `Partidas`.