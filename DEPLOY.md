# Deploy na ShardCloud com VPS Ubuntu 24.04

Este guia foi feito para este projeto.

Objetivo final:

- publicar o portal em `https://vctresenha.fun`
- ativar HTTPS
- conectar Discord OAuth e captcha ao dominio real
- deixar o portal rodando sozinho na VPS
- deixar o bot do Discord conectado sozinho na VPS
- preparar o app desktop para falar com o dominio em vez de `localhost`

## 1. O que voce precisa ter pronto

Antes de comecar, confirme estes itens:

- VPS Ubuntu 24.04 criada na ShardCloud
- dominio `vctresenha.fun` apontando para o IP da VPS
- acesso SSH da VPS: usuario e senha ou chave
- projeto enviado para a VPS ou hospedado em um repositorio Git
- token do bot do Discord
- credenciais novas do Discord OAuth
- credenciais novas do Cloudflare Turnstile

Importante:

- As chaves atuais no arquivo `config/app_settings.json` ja foram expostas durante os testes locais.
- Antes de publicar, gere novas chaves no Discord e no Turnstile.

## 2. Visao geral do que vamos fazer

Voce vai seguir esta ordem:

1. entrar na VPS
2. instalar Python, Git e Caddy
3. copiar o projeto para a VPS
4. criar o ambiente virtual Python
5. instalar as dependencias do projeto
6. ajustar `config/app_settings.json` para producao
7. testar o portal localmente dentro da VPS
8. criar um servico `systemd` para deixar o portal sempre ligado
9. criar um servico `systemd` para deixar o bot do Discord sempre ligado
10. configurar o Caddy para expor o site em HTTPS
11. ajustar Discord OAuth e Turnstile para o dominio real
12. testar o site no navegador
13. trocar o app desktop para usar `https://vctresenha.fun`

## 3. Entrar na VPS

No seu computador Windows, abra PowerShell e rode:

```powershell
ssh root@IP_DA_VPS
```

Se a ShardCloud tiver fornecido outro usuario, troque `root` pelo usuario correto.

Na primeira conexao, confirme com `yes`.

## 4. Atualizar o sistema e instalar os pacotes

Dentro da VPS, rode estes comandos, um por vez:

```bash
apt update
apt upgrade -y
apt install -y python3 python3-venv python3-pip git unzip caddy
```

Se voce quiser ativar o firewall basico do Ubuntu, rode tambem:

```bash
ufw allow OpenSSH
ufw allow 80
ufw allow 443
ufw enable
```

Se o sistema pedir confirmacao, responda `y`.

## 5. Colocar o projeto na VPS

Voce tem dois caminhos.

### Opcao A: usando Git

Se o projeto estiver no GitHub, GitLab ou outro Git remoto:

```bash
cd /opt
git clone URL_DO_REPOSITORIO vctresenha
cd /opt/vctresenha
```

### Opcao B: enviando a pasta do projeto

Se o projeto esta so no seu PC, use WinSCP, FileZilla ou outro cliente SFTP para enviar a pasta inteira para:

```text
/opt/vctresenha
```

No fim dessa etapa, estes arquivos precisam existir na VPS:

- `portal_main.py`
- `requirements.txt`
- pasta `src`
- pasta `config`
- pasta `assets`

Voce pode conferir com:

```bash
cd /opt/vctresenha
ls
```

## 6. Criar o ambiente virtual Python

Ainda dentro de `/opt/vctresenha`, rode:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Se aparecer algum erro na instalacao, pare aqui e corrija isso antes de seguir.

Importante:

- nao rode `pip install -r requirements.txt` fora da `.venv`
- no Ubuntu 24.04, instalar com o `pip` do sistema pode falhar com `externally-managed-environment`
- o comando certo e sempre usar o Python da virtualenv ou ativar a `.venv` antes

Se quiser rodar sem ativar a virtualenv, use:

```bash
/opt/vctresenha/.venv/bin/python -m pip install --upgrade pip
/opt/vctresenha/.venv/bin/python -m pip install -r /opt/vctresenha/requirements.txt
```

## 7. Ajustar o config/app_settings.json para producao

Abra o arquivo:

```bash
nano /opt/vctresenha/config/app_settings.json
```

No bloco `portal`, troque pelo menos estes valores:

```json
"discord_bot": {
  "enabled": true,
  "token": "SEU_BOT_TOKEN",
  "status": "online",
  "activity_type": "watching",
  "activity_text": "VCT da Resenha"
},
"portal": {
  "base_url": "https://vctresenha.fun",
  "database_path": "data/portal.sqlite3",
  "admin_token": "COLOQUE_UM_TOKEN_FORTE_AQUI",
  "session_secret": "COLOQUE_UM_SEGREDO_FORTE_AQUI",
  "discord_client_id": "SEU_NOVO_CLIENT_ID",
  "discord_client_secret": "SEU_NOVO_CLIENT_SECRET",
  "discord_redirect_uri": "https://vctresenha.fun/auth/discord/callback",
  "turnstile_site_key": "SUA_NOVA_SITE_KEY",
  "turnstile_secret_key": "SUA_NOVA_SECRET_KEY",
  "logo_asset": "assets/vctdaresenha.png"
}
```

Se quiser gerar valores fortes para `admin_token` e `session_secret`, rode este comando duas vezes:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Para salvar no `nano`:

1. aperte `Ctrl + O`
2. aperte `Enter`
3. aperte `Ctrl + X`

## 8. Testar o portal localmente na VPS

Ative o ambiente e rode o portal:

```bash
cd /opt/vctresenha
source .venv/bin/activate
python portal_main.py
```

Agora abra uma segunda conexao SSH na VPS e rode:

```bash
curl http://127.0.0.1:8000/api/health
```

Se estiver tudo certo, o retorno deve ser parecido com:

```json
{"status":"ok"}
```

Se funcionou, volte para a primeira aba e pare o processo com `Ctrl + C`.

## 9. Criar o servico para o portal iniciar sozinho

Crie o arquivo do servico:

```bash
nano /etc/systemd/system/vctresenha-portal.service
```

Cole este conteudo:

```ini
[Unit]
Description=VCT da Resenha Portal
After=network.target

[Service]
WorkingDirectory=/opt/vctresenha
ExecStart=/opt/vctresenha/.venv/bin/python /opt/vctresenha/portal_main.py
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
```

Salve e saia.

Agora ative o servico:

```bash
systemctl daemon-reload
systemctl enable vctresenha-portal
systemctl start vctresenha-portal
systemctl status vctresenha-portal
```

O ideal e aparecer `active (running)`.

Para ver os logs:

```bash
journalctl -u vctresenha-portal -f
```

Para sair dessa visualizacao, aperte `Ctrl + C`.

## 10. Criar o servico para o bot iniciar sozinho

Crie o arquivo do servico:

```bash
nano /etc/systemd/system/vctresenha-discord-bot.service
```

Cole este conteudo:

```ini
[Unit]
Description=VCT da Resenha Discord Bot
After=network.target

[Service]
WorkingDirectory=/opt/vctresenha
ExecStart=/opt/vctresenha/.venv/bin/python /opt/vctresenha/discord_bot_main.py
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
```

Salve e saia.

Agora ative o servico:

```bash
systemctl daemon-reload
systemctl enable vctresenha-discord-bot
systemctl start vctresenha-discord-bot
systemctl status vctresenha-discord-bot
```

O ideal e aparecer `active (running)`.

Para reiniciar depois de qualquer ajuste no bot ou no `config/app_settings.json`, use:

```bash
systemctl restart vctresenha-discord-bot
systemctl status vctresenha-discord-bot
```

Para ver os logs:

```bash
journalctl -u vctresenha-discord-bot -f
```

Se o bot nao subir, o primeiro ponto para conferir e se `discord_bot.enabled` esta como `true` e se `discord_bot.token` foi preenchido corretamente no `config/app_settings.json`.

Se o log mostrar `ModuleNotFoundError: No module named 'discord'`, rode exatamente isto:

```bash
systemctl stop vctresenha-discord-bot
cd /opt/vctresenha
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip show discord.py
python discord_bot_main.py
```

O comando `python -m pip show discord.py` precisa listar o pacote instalado.

Se ele ainda disser `Package(s) not found`, instale manualmente:

```bash
cd /opt/vctresenha
source .venv/bin/activate
python -m pip install discord.py
python -m pip show discord.py
```

Se o teste manual com `python discord_bot_main.py` passar ou mudar para outro erro, volte para o servico:

```bash
systemctl daemon-reload
systemctl restart vctresenha-discord-bot
systemctl status vctresenha-discord-bot
journalctl -u vctresenha-discord-bot -n 50 --no-pager
```

Se precisar confirmar qual interpretador o servico esta usando, rode:

```bash
systemctl cat vctresenha-discord-bot
```

O `ExecStart` precisa estar assim:

```ini
ExecStart=/opt/vctresenha/.venv/bin/python /opt/vctresenha/discord_bot_main.py
```

## 11. Configurar o site com HTTPS usando Caddy

Abra o arquivo de configuracao do Caddy:

```bash
nano /etc/caddy/Caddyfile
```

Cole isto:

```caddy
vctresenha.fun, www.vctresenha.fun {
    reverse_proxy 127.0.0.1:8000
}
```

Salve e saia.

Agora recarregue o Caddy:

```bash
systemctl restart caddy
systemctl enable caddy
systemctl status caddy
```

Teste o dominio:

```bash
curl https://vctresenha.fun/api/health
```

Se estiver tudo certo, deve responder:

```json
{"status":"ok"}
```

## 12. Ajustar Discord OAuth

Entre no Discord Developer Portal e abra sua aplicacao.

Configure a Redirect URI exatamente assim:

```text
https://vctresenha.fun/auth/discord/callback
```

Isso precisa ser identico ao valor em `config/app_settings.json`.

Se nao bater exatamente, o login com Discord vai falhar.

## 13. Ajustar o Cloudflare Turnstile

No painel do Turnstile, adicione estes dominios permitidos:

- `vctresenha.fun`
- `www.vctresenha.fun`

Depois copie a nova `site key` e a nova `secret key` para `config/app_settings.json`.

## 14. Testar o site completo

Abra no navegador:

- `https://vctresenha.fun`
- `https://vctresenha.fun/api/health`

Teste esta sequencia:

1. a pagina inicial abre sem erro
2. a logo aparece
3. o botao de Discord abre a autenticacao
4. o login volta para o site
5. o dashboard abre
6. o envio de time funciona
7. no app desktop, a aba Portal consegue listar, aprovar e recusar

## 15. Trocar o app desktop para o dominio real

No seu computador Windows, no arquivo `config/app_settings.json`, troque:

```json
"portal": {
  "base_url": "https://vctresenha.fun",
  "discord_redirect_uri": "https://vctresenha.fun/auth/discord/callback"
}
```

Depois gere uma build nova do app desktop para que ele pare de apontar para `localhost`.

## 16. Comandos de diagnostico

Se alguma coisa nao funcionar, estes sao os comandos mais uteis:

### Ver o status do portal

```bash
systemctl status vctresenha-portal
```

### Ver os logs do portal

```bash
journalctl -u vctresenha-portal -n 100 --no-pager
```

### Ver o status do bot do Discord

```bash
systemctl status vctresenha-discord-bot
```

### Ver os logs do bot do Discord

```bash
journalctl -u vctresenha-discord-bot -n 100 --no-pager
```

### Ver o status do Caddy

```bash
systemctl status caddy
```

### Testar o portal localmente na VPS

```bash
curl http://127.0.0.1:8000/api/health
```

### Testar o portal pelo dominio

```bash
curl https://vctresenha.fun/api/health
```

## 17. Como descobrir onde esta o erro

Use esta regra:

- se `curl http://127.0.0.1:8000/api/health` falhar, o problema esta no Python do portal
- se o `curl` local funcionar, mas `https://vctresenha.fun` falhar, o problema esta no Caddy, DNS ou firewall
- se o site abrir, mas o login do Discord falhar, o problema esta nas credenciais ou na Redirect URI
- se o captcha falhar, o problema esta no Turnstile e nos dominios permitidos
- se o bot ficar reiniciando no `systemd`, veja `journalctl -u vctresenha-discord-bot -n 100 --no-pager` e confirme que `discord.py` foi instalado dentro da `.venv`

## 18. Checklist final

Marque tudo isto antes de considerar a publicacao pronta:

- VPS acessivel por SSH
- projeto copiado para `/opt/vctresenha`
- `.venv` criado
- dependencias instaladas com sucesso
- `config/app_settings.json` atualizado para producao
- `curl http://127.0.0.1:8000/api/health` retornando `ok`
- servico `vctresenha-portal` ativo
- servico `vctresenha-discord-bot` ativo
- Caddy ativo
- `curl https://vctresenha.fun/api/health` retornando `ok`
- Redirect URI do Discord configurada
- dominio no Turnstile configurado
- login funcionando no navegador
- app desktop apontando para `https://vctresenha.fun`

## 19. Se voce quiser uma sequencia minima para copiar e colar

Use isso na VPS, em ordem:

```bash
apt update
apt upgrade -y
apt install -y python3 python3-venv python3-pip git unzip caddy
cd /opt
git clone URL_DO_REPOSITORIO vctresenha
cd /opt/vctresenha
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
nano /opt/vctresenha/config/app_settings.json
python portal_main.py
```

Depois do teste do `portal_main.py`, crie o servico e o Caddy conforme as secoes acima.

## 20. Melhor opcao para atualizar a VPS automaticamente

Se voce quer a melhor opcao, use este fluxo:

1. projeto hospedado no GitHub
2. clone Git do projeto na VPS em `/opt/vctresenha`
3. GitHub Actions fazendo SSH na VPS
4. script de deploy na VPS atualizando codigo, dependencias e servicos

Este repositorio ja inclui os arquivos prontos:

- `scripts/deploy_vps.sh`
- `.github/workflows/deploy-vps.yml`

O workflow roda a cada `push` na branch `main` e tambem pode ser disparado manualmente em `Actions` no GitHub.

## 21. Como preparar a VPS para deploy automatico

Na VPS, use clone Git em vez de subir pasta manualmente:

```bash
cd /opt
git clone URL_DO_REPOSITORIO vctresenha
cd /opt/vctresenha
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
chmod +x /opt/vctresenha/scripts/deploy_vps.sh
```

O script `scripts/deploy_vps.sh` faz isto automaticamente em cada deploy:

- `git fetch --all --prune`
- `git checkout main`
- `git pull --ff-only origin main`
- atualiza a `.venv`
- reinicia `vctresenha-portal`
- reinicia `vctresenha-discord-bot` se o servico existir

Se voce quiser testar manualmente na VPS antes de ligar o GitHub Actions:

```bash
cd /opt/vctresenha
/opt/vctresenha/scripts/deploy_vps.sh main
```

## 22. Como configurar o GitHub Actions

No GitHub, abra o repositorio e va em:

`Settings` -> `Secrets and variables` -> `Actions`

Crie estes secrets:

- `VPS_HOST`: IP ou dominio da VPS
- `VPS_USER`: usuario SSH da VPS, por exemplo `root`
- `VPS_SSH_KEY`: chave privada SSH usada para conectar na VPS
- `VPS_PORT`: porta SSH, normalmente `22`

### Como gerar uma chave SSH so para deploy

No seu PC ou na propria VPS, gere uma chave dedicada:

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f github_actions_deploy
```

Isso vai criar dois arquivos:

- `github_actions_deploy`
- `github_actions_deploy.pub`

Adicione a chave publica na VPS:

```bash
mkdir -p ~/.ssh
cat github_actions_deploy.pub >> ~/.ssh/authorized_keys
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

Depois copie o conteudo do arquivo privado `github_actions_deploy` para o secret `VPS_SSH_KEY` no GitHub.

## 23. Como usar o deploy automatico

Depois que tudo estiver configurado, o fluxo fica assim:

```bash
git add .
git commit -m "atualização"
git push origin main
```

O GitHub Actions vai:

1. conectar por SSH na VPS
2. executar `/opt/vctresenha/scripts/deploy_vps.sh main`
3. atualizar o codigo
4. instalar dependencias novas
5. reiniciar portal e bot

Se quiser disparar sem fazer `push`, abra a aba `Actions` no GitHub e rode o workflow `Deploy VPS` manualmente.

No disparo manual, voce pode escolher a branch no campo `branch` do `workflow_dispatch`.

## 24. Como ver se o deploy automatico funcionou

No GitHub:

- abra a aba `Actions`
- entre na execucao mais recente do workflow `Deploy VPS`
- confira se o job terminou com sucesso

Na VPS:

```bash
systemctl status vctresenha-portal
systemctl status vctresenha-discord-bot
journalctl -u vctresenha-portal -n 50 --no-pager
journalctl -u vctresenha-discord-bot -n 50 --no-pager
```

## 25. Quando nao usar deploy automatico por GitHub Actions

Nao use esse fluxo se a VPS ainda estiver recebendo arquivo por upload manual e nao tiver um clone Git funcional em `/opt/vctresenha`.

Nesse caso, primeiro migre a VPS para um clone Git. Sem isso, o workflow nao tem de onde fazer `git pull`.