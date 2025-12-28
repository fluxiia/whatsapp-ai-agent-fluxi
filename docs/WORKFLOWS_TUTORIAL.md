# Tutorial dos Workflows GitHub Actions

Este guia explica como utilizar os três workflows disponíveis na pasta `.github/workflows` para validar, publicar imagens Docker e promover deploys do WhatsApp Agent.

## 1. Backend CI (`backend-ci.yml`)

### Quando roda
- Push para `main`, `master` ou `develop`.
- Pull Requests que alterem arquivos Python, `requirements*.txt` ou o próprio workflow.

### O que faz
1. Cria matriz com Python 3.11 e 3.12 em `ubuntu-latest`.
2. Usa cache de dependências baseado em `requirements.txt`.
3. Instala dependências + `pytest`.
4. Executa `pytest -q`.

### Como usar
- Garanta que seus testes estejam em `tests/` ou sigam a convenção do Pytest.
- Se precisar de dependências extras para o CI, adicione-as em `requirements.txt`.
- Para ignorar arquivos específicos em PRs, ajuste a lista `paths` do workflow.

## 2. Build e publicação Docker (`docker-publish.yml`)

### Quando roda
- Push de tags no formato `*.*.*` (ex.: `1.0.0`).
- Manualmente via "Run workflow".

### O que faz
1. Usa Buildx para construir a imagem definida pelo `matrix.service` (`whatsapp-agent`).
2. Extrai metadados (tags semver, `latest`, `sha`).
3. Faz login no `ghcr.io` e publica a imagem.
4. Gera SBOM (Syft), roda scan (Grype) e assina a imagem com Cosign.

### Pré-requisitos
- O repositório precisa ter permissão para publicar no GitHub Container Registry.
- Opcional: configure `GHCR_PAT` se quiser usar usuário diferente.

### Como usar
1. Crie uma tag semântica local: `git tag 1.0.0`.
2. Faça push: `git push origin 1.0.0`.
3. Acompanhe o workflow para obter o digest/tags geradas.

## 3. Deploy manual (`deploy.yml`)

### Quando roda
- Apenas via `workflow_dispatch` (manual).

### Inputs
- `environment`: `staging` ou `production` (pode ampliar a lista se quiser mais ambientes).
- `image_tag`: tag já publicada (ex.: `1.0.0`, `sha-XXXX`, `latest`).

### O que faz
1. Calcula referências de imagem (primária, tag composta, run number).
2. Faz login no `ghcr.io`.
3. Instala Cosign e verifica a assinatura da imagem origem.
4. Reaplica tags/push para o ambiente selecionado.
5. Executa comando de deploy configurado.

### Como configurar o deploy
- Defina o segredo `DEPLOY_COMMAND` no repositório ou ambiente do GitHub Actions.
- O comando deve aceitar um parâmetro (imagem final). Ex.: `DEPLOY_COMMAND="ssh user@server 'docker service update --image $1 app'"`.
- Se deixar o segredo vazio, o fluxo apenas promove as imagens e registra um aviso.

## Boas práticas gerais
1. **Versionamento claro**: use tags semânticas para mapear releases e facilitar o deploy.
2. **Ambientes GitHub**: crie ambientes `staging`/`production` com `secrets` e `deployment_branch_policy` se quiser mais segurança.
3. **Monitoramento**: ative notificações do Actions ou use `workflow_run` para alertas.
4. **Revisão**: sempre valide PRs com o Backend CI antes de gerar tags ou promover deploys.

---

Se adicionar novos serviços Docker ou fluxos, replique a estrutura dos arquivos existentes e atualize este tutorial.
