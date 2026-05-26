"""
Serviço para gerenciar comandos personalizáveis por sessão.
"""
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
from sessao.sessao_comando_model import SessaoComando, COMANDOS_PADRAO


class SessaoComandoService:
    """Serviço para gerenciar comandos por sessão."""
    
    @staticmethod
    def criar_comandos_padrao(db: Session, sessao_id: int) -> List[SessaoComando]:
        """
        Cria comandos padrão para uma nova sessão.
        """
        comandos_criados = []
        
        for comando_id, config in COMANDOS_PADRAO.items():
            comando = SessaoComando(
                sessao_id=sessao_id,
                comando_id=comando_id,
                gatilho=config["gatilho"],
                ativo=config["ativo"],
                resposta=config["resposta"],
                descricao=config["descricao"]
            )
            db.add(comando)
            comandos_criados.append(comando)
        
        db.commit()
        return comandos_criados
    
    @staticmethod
    def listar_por_sessao(db: Session, sessao_id: int) -> List[SessaoComando]:
        """Lista todos os comandos de uma sessão."""
        return db.query(SessaoComando).filter(
            SessaoComando.sessao_id == sessao_id
        ).all()
    
    @staticmethod
    def obter_comandos_dict(db: Session, sessao_id: int) -> Dict[str, SessaoComando]:
        """
        Retorna dicionário de comandos indexado por comando_id.
        Cria comandos padrão se não existirem e sincroniza novos.
        """
        comandos = SessaoComandoService.listar_por_sessao(db, sessao_id)
        
        # Se não tem comandos, criar todos os padrões
        if not comandos:
            comandos = SessaoComandoService.criar_comandos_padrao(db, sessao_id)
        else:
            # Sincronizar: adicionar comandos novos que não existem
            comandos_dict = {cmd.comando_id: cmd for cmd in comandos}
            for comando_id, config in COMANDOS_PADRAO.items():
                if comando_id not in comandos_dict:
                    novo_cmd = SessaoComando(
                        sessao_id=sessao_id,
                        comando_id=comando_id,
                        gatilho=config["gatilho"],
                        ativo=config["ativo"],
                        resposta=config["resposta"],
                        descricao=config["descricao"]
                    )
                    db.add(novo_cmd)
                    comandos.append(novo_cmd)
            db.commit()
        
        return {cmd.comando_id: cmd for cmd in comandos}
    
    @staticmethod
    def obter_por_gatilho(db: Session, sessao_id: int, texto: str) -> Optional[SessaoComando]:
        """
        Encontra um comando pelo gatilho.
        Retorna None se não encontrar ou se estiver inativo.
        """
        texto_lower = texto.strip().lower()
        
        # Buscar comandos da sessão
        comandos = SessaoComandoService.obter_comandos_dict(db, sessao_id)
        
        # PRIMEIRO: verificar comandos com match exato (prioridade sobre prefixo)
        for cmd in comandos.values():
            if not cmd.ativo:
                continue
            
            gatilho = cmd.gatilho.lower()
            
            # Match exato
            if texto_lower == gatilho:
                return cmd
            # Alias para ajuda
            elif cmd.comando_id == "ajuda" and texto_lower == "#help":
                return cmd
        
        # DEPOIS: verificar comando de troca de agente (prefixo)
        cmd_trocar = comandos.get("trocar_agente")
        if cmd_trocar and cmd_trocar.ativo:
            gatilho = cmd_trocar.gatilho.lower()
            if texto_lower.startswith(gatilho) and len(texto_lower) > len(gatilho):
                # Proteção: Ignorar se for comando do Coding Agent (ex: #code)
                try:
                    from agente.agente_model import Agente as AgenteModel
                    agente_coding = db.query(AgenteModel).filter(
                        AgenteModel.sessao_id == sessao_id,
                        AgenteModel.is_coding_agent == True
                    ).first()
                    if agente_coding:
                        from coding_agent.coding_service import CodingService
                        cs = CodingService.obter_sessao_por_agente(db, agente_coding.id)
                        if cs:
                            prefix_coding = (cs.routing_prefix or "#code").lower()
                            if texto_lower.startswith(prefix_coding):
                                return None
                except Exception:
                    if texto_lower.startswith("#code"):
                        return None
                        
                return cmd_trocar
        
        return None
    
    @staticmethod
    def extrair_codigo_agente(texto: str, gatilho: str) -> str:
        """Extrai o código do agente do comando de troca."""
        return texto.strip()[len(gatilho):]
    
    @staticmethod
    def atualizar(
        db: Session,
        sessao_id: int,
        comando_id: str,
        gatilho: Optional[str] = None,
        ativo: Optional[bool] = None,
        resposta: Optional[str] = None,
        descricao: Optional[str] = None
    ) -> Optional[SessaoComando]:
        """Atualiza um comando específico."""
        comando = db.query(SessaoComando).filter(
            SessaoComando.sessao_id == sessao_id,
            SessaoComando.comando_id == comando_id
        ).first()
        
        if not comando:
            # Criar se não existir
            config = COMANDOS_PADRAO.get(comando_id, {})
            comando = SessaoComando(
                sessao_id=sessao_id,
                comando_id=comando_id,
                gatilho=gatilho or config.get("gatilho", f"#{comando_id}"),
                ativo=ativo if ativo is not None else True,
                resposta=resposta or config.get("resposta"),
                descricao=descricao or config.get("descricao")
            )
            db.add(comando)
        else:
            if gatilho is not None:
                comando.gatilho = gatilho
            if ativo is not None:
                comando.ativo = ativo
            if resposta is not None:
                comando.resposta = resposta
            if descricao is not None:
                comando.descricao = descricao
        
        db.commit()
        db.refresh(comando)
        return comando
    
    @staticmethod
    def atualizar_todos(
        db: Session,
        sessao_id: int,
        comandos_config: Dict[str, Dict]
    ) -> List[SessaoComando]:
        """
        Atualiza todos os comandos de uma sessão.
        
        Args:
            comandos_config: Dict no formato {
                comando_id: {gatilho, ativo, resposta, descricao}
            }
        """
        atualizados = []
        
        for comando_id, config in comandos_config.items():
            cmd = SessaoComandoService.atualizar(
                db,
                sessao_id,
                comando_id,
                gatilho=config.get("gatilho"),
                ativo=config.get("ativo"),
                resposta=config.get("resposta"),
                descricao=config.get("descricao")
            )
            atualizados.append(cmd)
        
        return atualizados
    
    @staticmethod
    def formatar_resposta(resposta: str, variaveis: Dict[str, str]) -> str:
        """
        Formata a resposta substituindo variáveis.
        Ex: {agente_nome}, {agente_descricao}, {total_mensagens}
        """
        if not resposta:
            return ""
        
        for var, valor in variaveis.items():
            resposta = resposta.replace(f"{{{var}}}", str(valor or ""))
        
        return resposta
    
    @staticmethod
    def gerar_texto_ajuda(db: Session, sessao_id: int) -> str:
        """Gera o texto de ajuda com todos os comandos ativos."""
        comandos = SessaoComandoService.obter_comandos_dict(db, sessao_id)
        
        texto = "📚 *Comandos Disponíveis:*\n\n"
        
        for cmd in comandos.values():
            if not cmd.ativo:
                continue
            
            if cmd.comando_id == "trocar_agente":
                texto += f"🔄 *{cmd.gatilho}01, {cmd.gatilho}02...* - {cmd.descricao}\n"
            else:
                texto += f"▪️ *{cmd.gatilho}* - {cmd.descricao}\n"
        
        texto += "\n💬 Para conversar normalmente, basta enviar sua mensagem!"
        
        return texto
