# Correções de CVEs - WhatsApp AI Agent

## Resumo das Vulnerabilidades Identificadas

### ✅ Corrigidas

#### CVE-2025-62727 - Starlette DoS via Range Header
- **Severidade**: 7.5 HIGH
- **Pacote afetado**: `starlette` 0.39.0 - 0.49.0
- **Descrição**: Ataque DoS através de header HTTP Range malicioso que causa processamento quadrático
- **Correção aplicada**: Atualização do FastAPI para 0.127.0, que inclui Starlette 0.49.1+
- **Referência**: https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8

#### CVE-2025-8869 - pip Path Traversal
- **Severidade**: 5.9 MEDIUM
- **Pacote afetado**: `pip` < 25.3
- **Descrição**: Vulnerabilidade de path traversal no mecanismo de extração tar fallback
- **Correção aplicada**: Atualizar pip no ambiente de build/runtime para versão 25.3+
- **Nota**: Afeta apenas Python < 3.9.17, 3.10.12, 3.11.4, 3.12
- **Referência**: https://nvd.nist.gov/vuln/detail/CVE-2025-8869

### ⚠️ Sem Correção Disponível

#### CVE-2024-23342 - ecdsa Minerva Timing Attack
- **Severidade**: 7.4 HIGH
- **Pacote afetado**: `ecdsa` <= 0.19.1
- **Descrição**: Vulnerabilidade de timing attack (Minerva) em operações P-256 ECDSA
- **Status**: Projeto considera side-channel attacks fora do escopo - **sem fix planejado**
- **Mitigação**: 
  - Verificação de assinatura ECDSA não é afetada
  - Apenas geração de assinatura é vulnerável
  - Considerar substituir por biblioteca alternativa se crítico para seu caso de uso
- **Referência**: https://github.com/advisories/GHSA-wj6h-64fc-37mp

### 🔵 CVEs Go (Dependências Indiretas)

#### CVE-2025-61729 e CVE-2025-61727 - golang stdlib crypto/x509
- **Pacote afetado**: `golang/stdlib` 1.25.4 (usado por neonize/whatsmeow)
- **Descrição**: Vulnerabilidades em validação de certificados x509
- **Status**: Dependência indireta via `neonize` (biblioteca Go compilada)
- **Ação recomendada**: Aguardar atualização do pacote `neonize` que incluirá Go stdlib atualizado

## Mudanças Aplicadas

### requirements.txt
```diff
- fastapi==0.118.0
+ fastapi==0.127.0
```

### Dockerfile
Adicionar no build para garantir pip atualizado:
```dockerfile
RUN pip install --upgrade pip>=25.3
```

## Próximos Passos

1. **Testar compatibilidade**: Executar testes após atualização do FastAPI
2. **Monitorar neonize**: Verificar releases para atualização do Go stdlib
3. **Avaliar ecdsa**: Se a aplicação usa geração de assinatura ECDSA, considerar:
   - Migrar para `cryptography` (wrapper do OpenSSL)
   - Usar `pycryptodome`
   - Aceitar o risco documentado

## Comandos de Verificação

```bash
# Verificar versões instaladas
pip list | grep -E "fastapi|starlette|ecdsa|pip"

# Escanear novamente com Grype
grype dir:. --scope all-layers

# Executar testes
pytest -v
```

## Referências

- [Starlette Security Advisory](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8)
- [pip CVE-2025-8869](https://www.seal.security/blog/the-critical-gap-why-an-unreleased-pip-path-traversal-fix-cve-2025-8869-leaves-python-users-exposed-for-months)
- [ecdsa Minerva Attack](https://github.com/advisories/GHSA-wj6h-64fc-37mp)
- [FastAPI Release Notes](https://fastapi.tiangolo.com/release-notes/)
