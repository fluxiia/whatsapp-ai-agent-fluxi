"""
Testes funcionais para SessaoService + SessaoComandoService + SessaoTipoMensagemService.
"""
from __future__ import annotations

import pytest

from sessao.sessao_service import SessaoService, gerenciador_sessoes
from sessao.sessao_schema import SessaoCriar, SessaoAtualizar
from sessao.sessao_comando_service import SessaoComandoService
from sessao.sessao_tipo_mensagem_service import SessaoTipoMensagemService
from sessao.sessao_tipo_mensagem_model import TipoMensagemEnum


# Patch para que SessaoService.criar não tente criar agente de coding (depende de modelo Anthropic etc.)
@pytest.fixture(autouse=True)
def _stub_coding(monkeypatch):
    try:
        from coding_agent.coding_service import CodingService
        monkeypatch.setattr(CodingService, "criar_agente_coding_padrao",
                            lambda db, sid: None)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# SessaoService CRUD
# ═══════════════════════════════════════════════════════════════════════════

class TestSessaoCrud:
    def test_criar_sessao_whatsapp(self, db):
        s = SessaoService.criar(db, SessaoCriar(nome="wa_test"))
        assert s.id is not None
        assert s.nome == "wa_test"
        assert s.plataforma == "whatsapp"
        assert s.status == "desconectado"

    def test_criar_sessao_nome_duplicado(self, db):
        SessaoService.criar(db, SessaoCriar(nome="dup"))
        with pytest.raises(ValueError):
            SessaoService.criar(db, SessaoCriar(nome="dup"))

    def test_criar_sessao_plataforma_invalida(self, db):
        with pytest.raises(ValueError):
            SessaoService.criar(db, SessaoCriar(nome="x", plataforma="discord"))

    def test_criar_telegram_sem_token_falha(self, db):
        with pytest.raises(ValueError):
            SessaoService.criar(db, SessaoCriar(nome="tg", plataforma="telegram"))

    def test_listar_todas(self, db, sessao_teste):
        todas = SessaoService.listar_todas(db)
        assert any(s.id == sessao_teste.id for s in todas)

    def test_listar_apenas_ativas(self, db):
        # Cria sessão inativa diretamente para evitar criar agentes
        from sessao.sessao_model import Sessao
        s = Sessao(nome="inativa_x", plataforma="whatsapp", ativa=False, status="desconectado")
        db.add(s); db.commit()

        ativas = SessaoService.listar_todas(db, apenas_ativas=True)
        ids = [x.id for x in ativas]
        assert s.id not in ids

    def test_obter_por_id(self, db, sessao_teste):
        assert SessaoService.obter_por_id(db, sessao_teste.id).id == sessao_teste.id
        assert SessaoService.obter_por_id(db, 9999) is None

    def test_obter_por_nome(self, db, sessao_teste):
        assert SessaoService.obter_por_nome(db, sessao_teste.nome).id == sessao_teste.id

    def test_obter_por_telefone(self, db):
        from sessao.sessao_model import Sessao
        s = Sessao(nome="com_fone", plataforma="whatsapp",
                   telefone="5511999998888", status="conectado")
        db.add(s); db.commit()
        achada = SessaoService.obter_por_telefone(db, "5511999998888")
        assert achada is not None
        assert achada.id == s.id

    def test_atualizar(self, db, sessao_teste):
        a = SessaoService.atualizar(db, sessao_teste.id,
                                    SessaoAtualizar(auto_responder=False))
        assert a.auto_responder is False

    def test_atualizar_inexistente_retorna_none(self, db):
        assert SessaoService.atualizar(db, 999, SessaoAtualizar(nome="x")) is None

    def test_deletar(self, db, sessao_teste):
        sid = sessao_teste.id
        assert SessaoService.deletar(db, sid) is True
        assert SessaoService.obter_por_id(db, sid) is None

    def test_deletar_inexistente(self, db):
        assert SessaoService.deletar(db, 999) is False


# ═══════════════════════════════════════════════════════════════════════════
# GerenciadorSessoes
# ═══════════════════════════════════════════════════════════════════════════

class TestGerenciador:
    def test_adicionar_obter_remover(self):
        # estado limpo
        gerenciador_sessoes.clientes.clear()
        fake = object()
        gerenciador_sessoes.adicionar_cliente(42, fake)
        assert gerenciador_sessoes.obter_cliente(42) is fake
        gerenciador_sessoes.remover_cliente(42)
        assert gerenciador_sessoes.obter_cliente(42) is None
        # remover inexistente é silencioso
        gerenciador_sessoes.remover_cliente(999)


# ═══════════════════════════════════════════════════════════════════════════
# SessaoComandoService
# ═══════════════════════════════════════════════════════════════════════════

class TestComandos:
    def test_criar_comandos_padrao(self, db, sessao_teste):
        cmds = SessaoComandoService.criar_comandos_padrao(db, sessao_teste.id)
        assert len(cmds) >= 5
        ids = {c.comando_id for c in cmds}
        assert {"ativar", "desativar", "limpar", "ajuda", "status"}.issubset(ids)

    def test_obter_comandos_dict_cria_se_vazio(self, db, sessao_teste):
        cmds = SessaoComandoService.obter_comandos_dict(db, sessao_teste.id)
        assert "ajuda" in cmds
        assert cmds["ajuda"].gatilho == "#ajuda"

    def test_obter_por_gatilho_match_exato(self, db, sessao_teste):
        SessaoComandoService.criar_comandos_padrao(db, sessao_teste.id)
        cmd = SessaoComandoService.obter_por_gatilho(db, sessao_teste.id, "#ajuda")
        assert cmd is not None
        assert cmd.comando_id == "ajuda"

    def test_obter_por_gatilho_alias_help(self, db, sessao_teste):
        SessaoComandoService.criar_comandos_padrao(db, sessao_teste.id)
        cmd = SessaoComandoService.obter_por_gatilho(db, sessao_teste.id, "#help")
        assert cmd is not None
        assert cmd.comando_id == "ajuda"

    def test_obter_por_gatilho_inexistente(self, db, sessao_teste):
        SessaoComandoService.criar_comandos_padrao(db, sessao_teste.id)
        # texto sem prefixo "#" não dispara nenhum comando
        cmd = SessaoComandoService.obter_por_gatilho(db, sessao_teste.id, "ola tudo bem")
        assert cmd is None

    def test_obter_por_gatilho_trocar_agente(self, db, sessao_teste):
        SessaoComandoService.criar_comandos_padrao(db, sessao_teste.id)
        cmd = SessaoComandoService.obter_por_gatilho(db, sessao_teste.id, "#01")
        assert cmd is not None
        assert cmd.comando_id == "trocar_agente"

    def test_extrair_codigo_agente(self):
        codigo = SessaoComandoService.extrair_codigo_agente("#02", "#")
        assert codigo == "02"

    def test_atualizar_comando(self, db, sessao_teste):
        SessaoComandoService.criar_comandos_padrao(db, sessao_teste.id)
        atualizado = SessaoComandoService.atualizar(
            db, sessao_teste.id, "ajuda", gatilho="/help", ativo=False
        )
        assert atualizado.gatilho == "/help"
        assert atualizado.ativo is False

    def test_atualizar_cria_se_nao_existe(self, db, sessao_teste):
        novo = SessaoComandoService.atualizar(
            db, sessao_teste.id, "novissimo", gatilho="!novo", resposta="oi"
        )
        assert novo.id is not None
        assert novo.gatilho == "!novo"

    def test_formatar_resposta(self):
        r = SessaoComandoService.formatar_resposta(
            "Olá {nome}, agente: {agente}",
            {"nome": "Ana", "agente": "Fluxi"}
        )
        assert r == "Olá Ana, agente: Fluxi"

    def test_formatar_resposta_variavel_ausente(self):
        # variável não fornecida vira string vazia
        r = SessaoComandoService.formatar_resposta("X={x}", {"x": None})
        assert r == "X="

    def test_gerar_texto_ajuda(self, db, sessao_teste):
        texto = SessaoComandoService.gerar_texto_ajuda(db, sessao_teste.id)
        assert "Comandos" in texto
        assert "#ajuda" in texto


# ═══════════════════════════════════════════════════════════════════════════
# SessaoTipoMensagemService
# ═══════════════════════════════════════════════════════════════════════════

class TestTipoMensagem:
    def test_criar_configuracoes_padrao(self, db, sessao_teste):
        configs = SessaoTipoMensagemService.criar_configuracoes_padrao(
            db, sessao_teste.id
        )
        assert len(configs) == len(list(TipoMensagemEnum))

    def test_obter_por_tipo(self, db, sessao_teste):
        SessaoTipoMensagemService.criar_configuracoes_padrao(db, sessao_teste.id)
        cfg = SessaoTipoMensagemService.obter_por_tipo(db, sessao_teste.id, "audio")
        assert cfg is not None
        assert cfg.tipo == "audio"

    def test_atualizar_acao(self, db, sessao_teste):
        SessaoTipoMensagemService.criar_configuracoes_padrao(db, sessao_teste.id)
        atualizado = SessaoTipoMensagemService.atualizar(
            db, sessao_teste.id, "audio", "resposta_fixa", "Não posso ouvir áudio"
        )
        assert atualizado.acao == "resposta_fixa"
        assert atualizado.resposta_fixa == "Não posso ouvir áudio"

    def test_atualizar_cria_se_inexistente(self, db, sessao_teste):
        novo = SessaoTipoMensagemService.atualizar(
            db, sessao_teste.id, "novo_tipo", "ignorar"
        )
        assert novo.id is not None

    def test_atualizar_todos(self, db, sessao_teste):
        SessaoTipoMensagemService.criar_configuracoes_padrao(db, sessao_teste.id)
        result = SessaoTipoMensagemService.atualizar_todos(
            db, sessao_teste.id,
            {"audio": {"acao": "ignorar"}, "imagem": {"acao": "enviar_ia"}}
        )
        assert len(result) == 2

    def test_obter_acao_existente(self, db, sessao_teste):
        SessaoTipoMensagemService.criar_configuracoes_padrao(db, sessao_teste.id)
        r = SessaoTipoMensagemService.obter_acao(db, sessao_teste.id, "audio")
        assert "acao" in r

    def test_obter_acao_sem_config_usa_padrao(self, db, sessao_teste):
        r = SessaoTipoMensagemService.obter_acao(db, sessao_teste.id, "audio")
        assert r["acao"] == "enviar_ia"  # padrão para audio

    def test_obter_acao_tipo_invalido(self, db, sessao_teste):
        r = SessaoTipoMensagemService.obter_acao(db, sessao_teste.id, "inventado")
        assert r["acao"] == "ignorar"

    def test_obter_opcoes_disponiveis(self):
        opcoes = SessaoTipoMensagemService.obter_opcoes_disponiveis("audio")
        assert "ignorar" in opcoes
        assert "enviar_ia" in opcoes

    def test_obter_opcoes_tipo_invalido(self):
        opcoes = SessaoTipoMensagemService.obter_opcoes_disponiveis("xpto")
        assert opcoes == ["ignorar"]

    def test_deletar_por_sessao(self, db, sessao_teste):
        SessaoTipoMensagemService.criar_configuracoes_padrao(db, sessao_teste.id)
        n = SessaoTipoMensagemService.deletar_por_sessao(db, sessao_teste.id)
        assert n > 0
        assert SessaoTipoMensagemService.listar_por_sessao(db, sessao_teste.id) == []
