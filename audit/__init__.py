"""Audit trails imutaveis.

Tabelas append-only que gravam falhas/decisoes/eventos do agente pra fins
de diagnostico e compliance. Diferente de `log/` (logs operacionais), aqui
o registro eh estruturado e queryavel.

Hoje contem so `agent_failures` — falhas no pipeline de IA. Outras audit
tables (auth events, admin actions) podem entrar aqui depois.
"""
