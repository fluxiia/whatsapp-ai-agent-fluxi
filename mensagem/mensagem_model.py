"""
Modelo de dados para mensagens.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base


class Mensagem(Base):
    """
    Tabela de mensagens.
    Armazena todas as mensagens recebidas e enviadas.
    """
    __tablename__ = "mensagens"

    id = Column(Integer, primary_key=True, index=True)
    sessao_id = Column(Integer, ForeignKey("sessoes.id"), nullable=False, index=True)
    # Canal de origem ('whatsapp' | 'telegram'). Default 'whatsapp' p/ retrocompat.
    plataforma = Column(String(20), nullable=False, default="whatsapp", index=True)

    # Identificação
    telefone_cliente = Column(String(20), nullable=False, index=True)
    nome_cliente = Column(String(100), nullable=True)
    mensagem_id_whatsapp = Column(String(100), nullable=True, index=True)
    # Genéricos (espelham os campos legados durante a migração).
    chat_id = Column(String(100), nullable=True, index=True)
    mensagem_id_externo = Column(String(100), nullable=True, index=True)
    
    # Tipo e direção
    tipo = Column(String(20), nullable=False, default="texto")  # texto, imagem, documento, audio, video
    direcao = Column(String(10), nullable=False)  # recebida, enviada
    
    # Conteúdo
    conteudo_texto = Column(Text, nullable=True)
    conteudo_imagem_path = Column(String(500), nullable=True)  # Caminho local da imagem
    conteudo_imagem_base64 = Column(Text, nullable=True)  # Imagem em base64
    conteudo_imagem_url = Column(String(500), nullable=True)  # URL da imagem
    conteudo_mime_type = Column(String(100), nullable=True)
    
    # Metadados da conversa
    contexto = Column(JSON, nullable=True)  # Histórico de mensagens para contexto
    
    # Resposta do agente
    resposta_texto = Column(Text, nullable=True)
    resposta_tokens_input = Column(Integer, nullable=True)
    resposta_tokens_output = Column(Integer, nullable=True)
    resposta_tempo_ms = Column(Integer, nullable=True)
    resposta_modelo = Column(String(100), nullable=True)
    resposta_erro = Column(Text, nullable=True)
    
    # Ferramentas utilizadas
    ferramentas_usadas = Column(JSON, nullable=True)  # Lista de ferramentas chamadas
    
    # Status
    processada = Column(Boolean, default=False)
    respondida = Column(Boolean, default=False)
    
    # Timestamps
    criado_em = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    processado_em = Column(DateTime(timezone=True), nullable=True)
    respondido_em = Column(DateTime(timezone=True), nullable=True)
    
    # Relacionamentos
    sessao = relationship("Sessao", back_populates="mensagens")

    def __repr__(self):
        return f"<Mensagem(id={self.id}, telefone='{self.telefone_cliente}', tipo='{self.tipo}', direcao='{self.direcao}')>"
