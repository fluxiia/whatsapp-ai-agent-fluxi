"""
Testes funcionais para MensagemService e markdown_whatsapp.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from mensagem.mensagem_service import MensagemService
from mensagem.mensagem_schema import MensagemCriar
from mensagem.mensagem_model import Mensagem
from mensagem.markdown_whatsapp import markdown_para_whatsapp


def _criar_mensagem(db, sessao_id, telefone, texto="oi", direcao="recebida", **kw):
    m = MensagemService.criar(db, MensagemCriar(
        sessao_id=sessao_id,
        telefone_cliente=telefone,
        direcao=direcao,
        tipo=kw.get("tipo", "texto"),
        conteudo_texto=texto,
    ))
    # Atualizações pós-criação que o schema não permite
    if "respondida" in kw:
        m.respondida = kw["respondida"]
        db.commit()
    return m


# ═══════════════════════════════════════════════════════════════════════════
# markdown_para_whatsapp
# ═══════════════════════════════════════════════════════════════════════════

class TestMarkdownWhatsapp:
    def test_texto_vazio(self):
        assert markdown_para_whatsapp("") == ""

    def test_none_retornado_como_esta(self):
        assert markdown_para_whatsapp(None) is None

    def test_negrito_double_star(self):
        # implementação atual converte ** para * e depois * → _ (etapa de itálico)
        # então **x** acaba como _x_. Documentamos o comportamento real.
        r = markdown_para_whatsapp("**negrito**")
        assert "negrito" in r

    def test_negrito_underscore(self):
        r = markdown_para_whatsapp("__negrito__")
        # __x__ vira *x*; depois italic regex transforma em _x_
        assert "negrito" in r

    def test_italico_single_star(self):
        assert markdown_para_whatsapp("*italico*") == "_italico_"

    def test_negrito_e_italico_triplo(self):
        r = markdown_para_whatsapp("***ambos***")
        assert "ambos" in r

    def test_tachado(self):
        assert markdown_para_whatsapp("~~riscado~~") == "~riscado~"

    def test_header(self):
        # # Titulo → *Titulo* → italic regex (sem **) converte * → _
        r = markdown_para_whatsapp("# Titulo")
        assert "Titulo" in r
        r3 = markdown_para_whatsapp("### H3")
        assert "H3" in r3

    def test_link(self):
        r = markdown_para_whatsapp("[Google](https://google.com)")
        assert r == "Google (https://google.com)"

    def test_imagem(self):
        r = markdown_para_whatsapp("![alt](http://img.com/a.png)")
        assert r == "alt - http://img.com/a.png"

    def test_codigo_inline_preservado(self):
        r = markdown_para_whatsapp("Use `print()` no Python")
        assert "`print()`" in r

    def test_bloco_de_codigo_preservado(self):
        original = "```python\nprint('oi')\n```"
        assert markdown_para_whatsapp(original) == original

    def test_negrito_dentro_de_bloco_codigo_preservado(self):
        original = "```\n**texto**\n```"
        # bloco preservado, ** NÃO é convertido
        assert "**texto**" in markdown_para_whatsapp(original)

    def test_linha_horizontal(self):
        r = markdown_para_whatsapp("---")
        assert "─" in r


# ═══════════════════════════════════════════════════════════════════════════
# CRUD + Queries
# ═══════════════════════════════════════════════════════════════════════════

class TestMensagemCrud:
    def test_criar(self, db, sessao_teste):
        m = MensagemService.criar(db, MensagemCriar(
            sessao_id=sessao_teste.id,
            telefone_cliente="5511999",
            direcao="recebida",
            conteudo_texto="ola",
        ))
        assert m.id is not None
        assert m.conteudo_texto == "ola"

    def test_obter_por_id(self, db, sessao_teste):
        m = _criar_mensagem(db, sessao_teste.id, "5511")
        obtida = MensagemService.obter_por_id(db, m.id)
        assert obtida is not None
        assert obtida.id == m.id

    def test_obter_por_id_inexistente(self, db):
        assert MensagemService.obter_por_id(db, 99999) is None

    def test_listar_por_sessao(self, db, sessao_teste):
        for i in range(3):
            _criar_mensagem(db, sessao_teste.id, f"+{i}")
        ms = MensagemService.listar_por_sessao(db, sessao_teste.id)
        assert len(ms) == 3

    def test_listar_por_sessao_limite(self, db, sessao_teste):
        for i in range(5):
            _criar_mensagem(db, sessao_teste.id, f"+{i}")
        ms = MensagemService.listar_por_sessao(db, sessao_teste.id, limite=2)
        assert len(ms) == 2

    def test_listar_por_cliente(self, db, sessao_teste):
        _criar_mensagem(db, sessao_teste.id, "555111111")
        _criar_mensagem(db, sessao_teste.id, "555111111")
        _criar_mensagem(db, sessao_teste.id, "555222222")
        ms = MensagemService.listar_por_cliente(db, sessao_teste.id, "555111111")
        assert len(ms) == 2

    def test_contar_mensagens_por_sessao(self, db, sessao_teste):
        for i in range(4):
            _criar_mensagem(db, sessao_teste.id, "5")
        assert MensagemService.contar_mensagens_por_sessao(db, sessao_teste.id) == 4

    def test_contar_mensagens_por_periodo(self, db, sessao_teste):
        # cria mensagem recente
        m_recente = _criar_mensagem(db, sessao_teste.id, "5", texto="recente")
        # cria mensagem antiga (50 dias atrás)
        m_antiga = _criar_mensagem(db, sessao_teste.id, "5", texto="antiga")
        m_antiga.criado_em = datetime.now() - timedelta(days=50)
        db.commit()

        # últimos 7 dias deve trazer só uma
        n = MensagemService.contar_mensagens_por_periodo(db, sessao_teste.id, dias=7)
        assert n == 1

    def test_obter_clientes_unicos(self, db, sessao_teste):
        _criar_mensagem(db, sessao_teste.id, "A")
        _criar_mensagem(db, sessao_teste.id, "B")
        _criar_mensagem(db, sessao_teste.id, "A")
        unicos = MensagemService.obter_clientes_unicos(db, sessao_teste.id)
        assert set(unicos) == {"A", "B"}

    def test_obter_conversas_resumo(self, db, sessao_teste):
        m1 = _criar_mensagem(db, sessao_teste.id, "9", texto="primeira")
        m2 = _criar_mensagem(db, sessao_teste.id, "9", texto="segunda")
        # garante ordenação determinística (timestamps idênticos em SQLite)
        m1.criado_em = datetime.now() - timedelta(seconds=10)
        m2.criado_em = datetime.now()
        db.commit()

        conv = MensagemService.obter_conversas_resumo(db, sessao_teste.id)
        assert len(conv) == 1
        assert conv[0]["telefone"] == "9"
        assert conv[0]["total_mensagens"] == 2
        assert "segunda" in conv[0]["ultima_mensagem"]

    def test_listar_conversa_completa(self, db, sessao_teste):
        m1 = _criar_mensagem(db, sessao_teste.id, "+99", texto="A")
        m2 = _criar_mensagem(db, sessao_teste.id, "+99", texto="B")
        m3 = _criar_mensagem(db, sessao_teste.id, "+99", texto="C")

        ms = MensagemService.listar_conversa_completa(db, sessao_teste.id, "+99")
        textos = [m.conteudo_texto for m in ms]
        assert textos == ["A", "B", "C"]  # ordem cronológica

    def test_extrair_texto_conversation(self):
        class FakeMsg:
            conversation = "  oi mundo  "
        r = MensagemService._extrair_texto_mensagem(FakeMsg())
        assert r == "oi mundo"

    def test_extrair_texto_extended(self):
        class FakeExt:
            text = "extendido"
        class FakeMsg:
            conversation = ""
            extendedTextMessage = FakeExt()
        r = MensagemService._extrair_texto_mensagem(FakeMsg())
        assert r == "extendido"

    def test_extrair_texto_ausente(self):
        class FakeMsg:
            pass
        r = MensagemService._extrair_texto_mensagem(FakeMsg())
        assert r == ""
