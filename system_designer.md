# 🎨 Fluxi.IA — Design System & Component Library

Este é o **Guia Referencial e Library de Componentes** estrutural para gerar as interfaces da plataforma Fluxi.IA. Como o contexto da IA é limitado no longo prazo, todos os componentes padronizados a serem reutilizados *devem* seguir os blocos de HTML definidos aqui.

## ⚖️ Filosofia de Design: *Agent-Centric Mission Control*
- O `Workspace` foca exclusivamente no gerenciamento do Agente de IA.
- O canal (WhatsApp, Telegram) é apenas um gateway, listado sob a entidade **Agente**.
- **Regra de Ouro:** *Sem cores extravagantes, sem áreas enormes de white-space sem uso.* Componentes compactos (densidade de SaaS B2B), fontes contidas e colorização limitada a Badges e Botões de CTA (Call to Action).

---

## 🧱 1. Layout Base da Página (Page Header)

Toda nova página deve estender `base_modern.html` e usar este esqueleto para seu cabeçalho:

```html
{% extends "base_modern.html" %}

{% block title %}Título - Fluxi.IA{% endblock %}

{% block content %}
<div class="container">
    <!-- Page Header Menor e Contido -->
    <div class="flex items-center justify-between mb-lg" style="border-bottom: 1px solid var(--color-border); padding-bottom: var(--space-md);">
        <div>
            <h1 class="page-title" style="font-size: 1.25rem;">Título da Página</h1>
            <p class="breadcrumbs" style="margin-top: 2px;">Subtítulo ou contexto descritivo rápido</p>
        </div>
        <div class="flex items-center gap-sm">
            <button class="button is-outline is-small">Ação Secundária</button>
            <button class="button is-primary is-small">Ação Principal</button>
        </div>
    </div>
    
    <!-- Conteúdo em Grid ou Flex aqui -->
</div>
{% endblock %}
```

---

## 📐 2. Layout do Grid (Grid System)

Para estruturar colunas divididas simetricamente, usamos classes CSS grid nativas do `modern.css`.
O padrão "Mission Control" adora um layout `2/3` e `1/3` (Esquerda: Conteúdo, Direita: Insights).

```html
<div class="grid grid-cols-3">
    <!-- Ocupa 2 colunas: A área de trabalho e listagens -->
    <div style="grid-column: span 2;" class="flex flex-col gap-lg">
        [Tabelas e Listagens Form]
    </div>
    
    <!-- Ocupa 1 coluna (Lateral Direita): Métricas ou Dicas rápidas -->
    <div class="flex flex-col gap-lg">
        [Mini Métricas e System Health]
    </div>
</div>
```

---

## 🏗 3. Componentes Genéricos de Estrutura

### 3.1. Box Padrão (Cartão)
Sempre use `.box` em oposição a `.card` gigante quando o intuito for agrupar informações técnicas (uma lista de configurações, uma lista de métricas).

```html
<div class="box" style="padding: var(--space-md) var(--space-lg);">
    <h3 style="font-size: 0.8125rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-text-secondary); margin-bottom: var(--space-md);">
        Título do Box
    </h3>
    <p>Conteúdo interno padrão.</p>
</div>
```

### 3.2. Alert/Info Box (Dicas do Sistema)
Quando precisar ensinar como funciona a Rota, a Ferramenta ou o Fluxo, utilize as cores de background tertiary sem bordas fortes. Não force "Amarelo/Vermelho" para dicas simples.

```html
<div class="box" style="padding: var(--space-md) var(--space-lg); background: var(--color-bg-tertiary); border: none;">
    <div class="flex items-center gap-sm mb-sm text-left">
        <i class="fas fa-lightbulb" style="color: var(--color-text-secondary);"></i>
        <strong style="font-size: 0.8125rem;">Título da Informação</strong>
    </div>
    <p style="font-size: 0.75rem; color: var(--color-text-secondary); line-height: 1.5;">
        Instrução descritiva de como a <strong>Ferramenta</strong> opera neste contexto.
    </p>
</div>
```

---

## 📄 4. Tabelas de Listagem (Data Tables)

Tabelas não devem usar cores zebradas extravagantes. Linha inferior divisória limpa, cabeçalhos em cinza e alinhamento preciso das ações do seu lado direito.

```html
<div class="card" style="border-radius: var(--radius-lg); overflow: hidden;">
    <!-- HEADER DA TABELA -->
    <div class="card-header flex items-center justify-between" style="padding: var(--space-md) var(--space-lg); border-bottom: 1px solid var(--color-border); background: var(--color-surface);">
        <h2 class="card-header-title" style="font-size: 1rem;">
            <i class="fas fa-list" style="margin-right: 6px; color: var(--color-text-secondary);"></i> Itens
        </h2>
        <a href="/novo" class="button is-outline is-small">Criar</a>
    </div>
    
    <!-- CORPO DA TABELA -->
    <div class="card-content" style="padding: 0;">
        <table class="table" style="font-size: 0.875rem; width: 100%; text-align: left;">
            <thead style="background: var(--color-bg-secondary);">
                <tr>
                    <th style="padding: var(--space-sm) var(--space-lg); font-weight: 500; font-size: 0.75rem; color: var(--color-text-secondary); text-transform: uppercase; letter-spacing: 0.05em;">Nome</th>
                    <th style="padding: var(--space-sm); font-weight: 500; font-size: 0.75rem; color: var(--color-text-secondary); text-transform: uppercase;">Status</th>
                    <th class="text-right" style="padding: var(--space-sm) var(--space-lg); font-weight: 500; font-size: 0.75rem; color: var(--color-text-secondary); text-transform: uppercase;">Ações</th>
                </tr>
            </thead>
            <tbody>
                <tr style="border-bottom: 1px solid var(--color-border);">
                    <td style="padding: var(--space-sm) var(--space-lg); font-weight: 500;">Agente Financeiro</td>
                    <td>
                        <!-- Status Badge Simples -->
                        <div class="flex items-center gap-xs" style="color: var(--color-success); font-weight: 500; font-size: 0.8125rem;">
                            <div style="width: 6px; height: 6px; border-radius: 50%; background: var(--color-success);"></div> Conectado
                        </div>
                    </td>
                    <td class="text-right" style="padding: var(--space-sm) var(--space-lg);">
                        <div class="flex items-center justify-end gap-xs">
                            <button class="button is-outline is-small" style="padding: var(--space-xs); border: none;">
                                <i class="fas fa-edit" style="color: var(--color-text-secondary);"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>
</div>
```

---

## 📝 5. Formulários, Inputs e Wizards

Nunca use Formulários massivos verticais confusos. Integre o conceito de labels pequenos com dicas logo após o Input (`.form-hint`).

### 5.1. Formulário Padrão
```html
<form class="box" style="padding: var(--space-xl); border: none; box-shadow: var(--shadow-sm);">
    <div class="form-group mb-lg">
        <label style="display: block; font-size: 0.8125rem; font-weight: 600; color: var(--color-text-primary); margin-bottom: var(--space-xs);">
            Nome do Agente <span style="color: var(--color-error);">*</span>
        </label>
        <input type="text" class="input" placeholder="ex: Assistente Virtual" style="font-size: 0.9375rem; padding: 0.75rem 1rem; width: 100%;">
        <div class="form-hint" style="font-size: 0.75rem; color: var(--color-text-secondary); margin-top: 4px;">Apenas para controle interno.</div>
    </div>
    
    <div class="flex items-center justify-end gap-md">
       <button type="submit" class="button is-primary">Salvar Configuração</button>
    </div>
</form>
```

### 5.2. Seleção de Modelos / Providers (Cards Rádio Visuais)
Substituir dropdowns antiquados por "Tool Cards" com flexibilidade via grid, usado fortemente no menu de criação de agentes:

```html
<div class="tool-grid" style="display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-md);">
    <label class="tool-card selected" style="border: 1px solid var(--color-primary); background: var(--color-info-light); border-radius: var(--radius-lg); padding: var(--space-md); cursor: pointer; display: flex; align-items: flex-start; gap: var(--space-md);">
        <input type="radio" name="provider" value="openai" checked style="display: none;">
        <span style="font-size: 1.5rem;"><i class="fas fa-brain" style="color: var(--color-success);"></i></span>
        <div class="flex flex-col">
            <span style="font-weight: 600; font-size: 0.875rem;">GPT-4o Mini</span>
            <span style="font-size: 0.75rem; color: var(--color-text-secondary); margin-top: 2px;">Melhor custo x benefício</span>
        </div>
    </label>
</div>
```
*(Nota: Sempre requer JS atrelado para alternar a classe `.selected` entre os labels durante o `click`)*.

---

## 📊 6. Métricas Reduzidas Padrão (Sem botões gigantes coloridos)
Quando precisar demonstrar estatísticas, fuja do "Quadrado Verde Gigante da Morte". Use uma lista "System Health" moderna.

```html
<div class="flex flex-col gap-md">
    <!-- Metric Row 1 -->
    <div class="flex items-center justify-between">
        <div class="flex flex-col">
            <span style="font-size: 1.25rem; font-weight: 600;">{{ sessoes.ativas }}</span>
            <span style="font-size: 0.75rem; color: var(--color-text-secondary);">Sessões Ativas</span>
        </div>
        <i class="fas fa-plug" style="color: var(--color-text-muted);"></i>
    </div>
    <!-- Divisória suave -->
    <div style="height: 1px; background: var(--color-border); width: 100%;"></div>
    
    <!-- Metric Row 2 -->
    <div class="flex items-center justify-between">
        <div class="flex flex-col">
            <span style="font-size: 1.25rem; font-weight: 600;">99.8%</span>
            <span style="font-size: 0.75rem; color: var(--color-text-secondary);">Taxa de Entrega</span>
        </div>
        <i class="fas fa-check" style="color: var(--color-success);"></i>
    </div>
</div>
```

---

## 🔄 7. Fluxo de Execução Diária 
Para refatorar as páginas (ex: `pages/ferramentas`, `pages/RAG`), os passos que a IA deverá sempre executar são:
1. Ler o arquivo `.html` original para não perder nenhuma tag Jinja2 e rotas de action method.
2. Ler `/system_designer.md` (este documento).
3. Reescrever o frontend sem frameworks antigos usando os layouts exatos acima.
4. Preservar rigorosamente as Lógicas, Links, For Loops e `{{ variáveis jinja }}` no ato.
