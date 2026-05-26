"""
Router para o wizard de criação de ferramentas.
Usa sessão para armazenar dados entre steps.
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional
import json

from database import get_db
from ferramenta.ferramenta_service import FerramentaService
from ferramenta.ferramenta_schema import FerramentaCriar
from ferramenta.ferramenta_model import ToolType, ToolScope, OutputDestination, ChannelType
from ferramenta.ferramenta_variavel_service import FerramentaVariavelService
from config.config_service import ConfiguracaoService
from log.log_service import fluxi_log

router = APIRouter(prefix="/ferramentas/wizard", tags=["Wizard Ferramentas"])
templates = Jinja2Templates(directory="templates")

# Cache em memória para test_result (evita problema de sessão)
_test_results_cache = {}


def get_wizard_data(request: Request) -> dict:
    """Obtém dados do wizard da sessão."""
    if 'wizard_ferramenta' not in request.session:
        request.session['wizard_ferramenta'] = {}
    return dict(request.session['wizard_ferramenta'])


def save_wizard_data(request: Request, data: dict):
    """Salva dados do wizard na sessão."""
    import json
    # Serializar e desserializar para garantir que é serializável
    serialized = json.dumps(data, default=str)
    deserialized = json.loads(serialized)
    request.session['wizard_ferramenta'] = deserialized


def clear_wizard_data(request: Request):
    """Limpa dados do wizard da sessão."""
    if 'wizard_ferramenta' in request.session:
        del request.session['wizard_ferramenta']


# ==================== STEP 1: Definição Básica ====================

@router.get("/step1")
async def wizard_step1_get(request: Request):
    """Exibe Step 1 - Definição Básica."""
    wizard_data = get_wizard_data(request)
    return templates.TemplateResponse("ferramenta/wizard/step1.html", {
        "request": request,
        "step_atual": 1,
        "wizard_data": wizard_data
    })


@router.post("/step1")
async def wizard_step1_post(
    request: Request,
    nome: str = Form(...),
    descricao: str = Form(...),
    tool_type: str = Form(...),
    tool_scope: str = Form(...)
):
    """Processa Step 1 e vai para Step 2."""
    wizard_data = get_wizard_data(request)
    
    # Salvar dados
    wizard_data.update({
        'nome': nome,
        'descricao': descricao,
        'tool_type': tool_type,
        'tool_scope': tool_scope
    })
    
    save_wizard_data(request, wizard_data)
    return RedirectResponse(url="/ferramentas/wizard/step2", status_code=303)


# ==================== STEP 2: Parâmetros ====================

@router.get("/step2")
async def wizard_step2_get(request: Request):
    """Exibe Step 2 - Parâmetros."""
    wizard_data = get_wizard_data(request)
    
    # Inicializar params se não existir
    if 'params' not in wizard_data:
        wizard_data['params'] = {}
    
    return templates.TemplateResponse("ferramenta/wizard/step2.html", {
        "request": request,
        "step_atual": 2,
        "wizard_data": wizard_data
    })


@router.post("/step2")
async def wizard_step2_post(
    request: Request,
    voltar: Optional[str] = Form(None),
    continuar: Optional[str] = Form(None),
    adicionar_param: Optional[str] = Form(None),
    remover_param: Optional[str] = Form(None),
    param_nome: Optional[str] = Form(None),
    param_type: Optional[str] = Form(None),
    param_required: Optional[str] = Form(None),
    param_description: Optional[str] = Form(None),
    param_options: Optional[str] = Form(None),
    param_item_type: Optional[str] = Form(None)
):
    """Processa Step 2."""
    wizard_data = get_wizard_data(request)
    
    if 'params' not in wizard_data:
        wizard_data['params'] = {}
    
    # Voltar
    if voltar:
        return RedirectResponse(url="/ferramentas/wizard/step1", status_code=303)
    
    # Adicionar parâmetro
    if adicionar_param and param_nome:
        param_config = {
            'type': param_type,
            'required': param_required == 'true',
            'description': param_description or ''
        }
        
        # Adicionar opções para enum
        if param_type == 'enum' and param_options:
            param_config['options'] = [opt.strip() for opt in param_options.split(',')]
        
        # Adicionar item_type para array
        if param_type == 'array' and param_item_type:
            param_config['item_type'] = param_item_type
        
        wizard_data['params'][param_nome] = param_config
        save_wizard_data(request, wizard_data)
        return RedirectResponse(url="/ferramentas/wizard/step2", status_code=303)
    
    # Remover parâmetro
    if remover_param:
        if remover_param in wizard_data['params']:
            del wizard_data['params'][remover_param]
        save_wizard_data(request, wizard_data)
        return RedirectResponse(url="/ferramentas/wizard/step2", status_code=303)
    
    # Continuar
    if continuar:
        save_wizard_data(request, wizard_data)
        return RedirectResponse(url="/ferramentas/wizard/step3", status_code=303)
    
    return RedirectResponse(url="/ferramentas/wizard/step2", status_code=303)


# ==================== STEP 3: Configuração ====================

@router.get("/step3")
async def wizard_step3_get(request: Request):
    """Exibe Step 3 - Configuração."""
    wizard_data = get_wizard_data(request)
    return templates.TemplateResponse("ferramenta/wizard/step3.html", {
        "request": request,
        "step_atual": 3,
        "wizard_data": wizard_data
    })


@router.post("/step3")
async def wizard_step3_post(
    request: Request,
    voltar: Optional[str] = Form(None),
    continuar: Optional[str] = Form(None),
    # CURL
    curl_command: Optional[str] = Form(None),
    tokens_data: Optional[str] = Form(None),
    # Campos CODE
    codigo_python: Optional[str] = Form(None),
    substituir: Optional[str] = Form(None)
):
    """Processa Step 3."""
    wizard_data = get_wizard_data(request)
    
    if voltar:
        return RedirectResponse(url="/ferramentas/wizard/step2", status_code=303)
    
    if continuar:
        # Salvar configuração baseado no tipo
        if wizard_data.get('tool_type') == 'web':
            wizard_data['curl_command'] = curl_command
            wizard_data['substituir'] = True  # Sempre true para CURL
            # Salvar tokens
            if tokens_data:
                wizard_data['tokens'] = tokens_data
        else:  # code
            wizard_data.update({
                'codigo_python': codigo_python,
                'substituir': substituir == 'true'
            })
        
        save_wizard_data(request, wizard_data)
        return RedirectResponse(url="/ferramentas/wizard/step4", status_code=303)
    
    return RedirectResponse(url="/ferramentas/wizard/step3", status_code=303)


# ==================== STEP 4: Testar ====================

@router.get("/step4")
async def wizard_step4_get(request: Request):
    """Exibe Step 4 - Testar."""
    wizard_data = get_wizard_data(request)
    
    # Buscar test_result do cache ao invés da sessão
    test_result = _test_results_cache.get('last_test_result')
    last_execution_id = _test_results_cache.get('last_execution_id', 'N/A')
    
    fluxi_log.info("ferramenta", "wizard", "Renderizando Step 4", extra={"execution_id": last_execution_id})
    if test_result:
        if isinstance(test_result, dict) and 'erro' not in test_result:
            fluxi_log.info("ferramenta", "wizard", "test_result OK", extra={"num_chaves": len(test_result)})
        else:
            fluxi_log.warning("ferramenta", "wizard", "test_result com erro")
    
    return templates.TemplateResponse("ferramenta/wizard/step4.html", {
        "request": request,
        "step_atual": 4,
        "wizard_data": wizard_data,
        "test_result": test_result
    })


@router.post("/step4/testar")
async def wizard_step4_testar(request: Request, db: Session = Depends(get_db)):
    """Executa teste da ferramenta."""
    import uuid
    execution_id = str(uuid.uuid4())[:8]
    fluxi_log.info("ferramenta", "wizard", "Nova execucao de teste", extra={"execution_id": execution_id})
    
    wizard_data = get_wizard_data(request)
    form_data = await request.form()
    
    # Montar argumentos de teste
    test_args = {}
    for key, value in form_data.items():
        if key.startswith('test_'):
            param_name = key[5:]  # Remove 'test_'
            # Converter tipos baseado nos params
            if wizard_data.get('params') and param_name in wizard_data['params']:
                param_config = wizard_data['params'][param_name]
                param_type = param_config.get('type', 'string')
                
                if param_type == 'int':
                    test_args[param_name] = int(value) if value else 0
                elif param_type == 'float':
                    test_args[param_name] = float(value) if value else 0.0
                elif param_type == 'bool':
                    test_args[param_name] = value == 'true'
                elif param_type == 'array':
                    test_args[param_name] = [v.strip() for v in value.split(',')]
                else:
                    test_args[param_name] = value
            else:
                test_args[param_name] = value
    
    # Executar ferramenta de verdade
    try:
        import httpx
        
        if wizard_data.get('tool_type') == 'web':
            # Executar requisição HTTP usando CURL
            from ferramenta.curl_parser import CurlParser
            from ferramenta.ferramenta_service import FerramentaService
            
            curl = wizard_data.get('curl_command', '')
            if not curl:
                test_result = {"erro": "Nenhum comando CURL configurado"}
            else:
                # Substituir variáveis no CURL
                curl = FerramentaService.substituir_variaveis(curl, test_args, {})
                
                # Parse CURL
                parsed = CurlParser.parse_curl(curl)
                
                # Executar requisição baseado no CURL parseado
                method = parsed.get('method', 'GET')
                url = parsed.get('url', '')
                headers = parsed.get('headers', {})
                query_params = parsed.get('query_params', {})
                body = parsed.get('body')
                
                if not url:
                    test_result = {"erro": "URL não encontrada no CURL"}
                else:
                    # Preparar body
                    json_body = None
                    if body:
                        try:
                            json_body = json.loads(body)
                        except json.JSONDecodeError as e:
                            _test_results_cache['last_test_result'] = {"erro": f"JSON inválido no body: {str(e)}"}
                            _test_results_cache['last_execution_id'] = execution_id
                            return RedirectResponse(url="/ferramentas/wizard/step4", status_code=303)
                    
                    # Obter timeout de teste configurado
                    timeout_teste = ConfiguracaoService.obter_valor(db, "ferramenta_timeout_teste", 10)
                    
                    async with httpx.AsyncClient() as client:
                        if method == "GET":
                            response = await client.get(url, headers=headers, params=query_params, timeout=float(timeout_teste))
                        elif method == "POST":
                            response = await client.post(url, headers=headers, params=query_params, json=json_body, timeout=float(timeout_teste))
                        elif method == "PUT":
                            response = await client.put(url, headers=headers, params=query_params, json=json_body, timeout=float(timeout_teste))
                        elif method == "PATCH":
                            response = await client.patch(url, headers=headers, params=query_params, json=json_body, timeout=float(timeout_teste))
                        elif method == "DELETE":
                            response = await client.delete(url, headers=headers, params=query_params, timeout=float(timeout_teste))
                        else:
                            raise ValueError(f"Método {method} não suportado")
                        
                        # Processar resposta
                        if response.status_code >= 200 and response.status_code < 300:
                            try:
                                test_result = response.json()
                            except json.JSONDecodeError:
                                test_result = {"resposta": response.text}
                        else:
                            test_result = {
                                "erro": f"HTTP {response.status_code}",
                                "mensagem": response.text
                            }
        
        elif wizard_data.get('tool_type') == 'code':
            # Executar código Python
            codigo = wizard_data.get('codigo_python', '')
            
            # Namespace para execução
            namespace = {
                'argumentos': test_args,
                'resultado': None,
                'datetime': __import__('datetime'),
                'json': json,
                'httpx': httpx
            }
            
            # Executar código
            exec(codigo, namespace)
            
            # Capturar resultado
            test_result = namespace.get('resultado', {})
            if test_result is None:
                test_result = {"aviso": "Código executado mas variável 'resultado' não foi definida"}
        
        else:
            test_result = {"erro": "Tipo de ferramenta não definido"}
        
        # Salvar test_result em cache em memória (mais confiável que sessão)
        _test_results_cache['last_test_result'] = test_result
        _test_results_cache['last_execution_id'] = execution_id
        fluxi_log.info("ferramenta", "wizard", "test_result salvo em cache", extra={"execution_id": execution_id})
        
        # Salvar wizard_data SEM test_result (para economizar espaço na sessão)
        wizard_data['last_test_execution_id'] = execution_id
        save_wizard_data(request, wizard_data)
        
    except httpx.TimeoutException:
        fluxi_log.error("ferramenta", "execucao", "TimeoutException no teste", exc_info=True, extra={"execution_id": execution_id})
        timeout_teste = ConfiguracaoService.obter_valor(db, "ferramenta_timeout_teste", 10)
        _test_results_cache['last_test_result'] = {"erro": f"Timeout na requisição ({timeout_teste}s)"}
        _test_results_cache['last_execution_id'] = execution_id
    except Exception as e:
        fluxi_log.error("ferramenta", "execucao", "Erro ao executar teste", exc_info=True, extra={"execution_id": execution_id})
        _test_results_cache['last_test_result'] = {"erro": f"Erro ao executar: {str(e)}"}
        _test_results_cache['last_execution_id'] = execution_id
    
    return RedirectResponse(url="/ferramentas/wizard/step4", status_code=303)


@router.post("/step4/voltar")
async def wizard_step4_voltar(request: Request):
    """Volta para step 3."""
    return RedirectResponse(url="/ferramentas/wizard/step3", status_code=303)


@router.post("/step4/continuar")
async def wizard_step4_continuar(request: Request):
    """Continua para step 5."""
    return RedirectResponse(url="/ferramentas/wizard/step5", status_code=303)


# ==================== STEP 5: Mapeamento ====================

@router.get("/step5")
async def wizard_step5_get(request: Request):
    """Exibe Step 5 - Mapeamento."""
    wizard_data = get_wizard_data(request)
    # Adicionar test_result do cache
    wizard_data['test_result'] = _test_results_cache.get('last_test_result')
    return templates.TemplateResponse("ferramenta/wizard/step5.html", {
        "request": request,
        "step_atual": 5,
        "wizard_data": wizard_data
    })


@router.post("/step5")
async def wizard_step5_post(
    request: Request,
    voltar: Optional[str] = Form(None),
    pular: Optional[str] = Form(None),
    continuar: Optional[str] = Form(None),
    response_map: Optional[str] = Form(None)
):
    """Processa Step 5."""
    wizard_data = get_wizard_data(request)
    
    if voltar:
        return RedirectResponse(url="/ferramentas/wizard/step4", status_code=303)
    
    if pular or continuar:
        # Salvar mapeamento se fornecido
        if response_map:
            wizard_data['response_map'] = response_map
        
        save_wizard_data(request, wizard_data)
        return RedirectResponse(url="/ferramentas/wizard/step6", status_code=303)
    
    return RedirectResponse(url="/ferramentas/wizard/step5", status_code=303)


# ==================== STEP 6: Destino ====================

@router.get("/step6")
async def wizard_step6_get(request: Request, db: Session = Depends(get_db)):
    """Exibe Step 6 - Destino."""
    wizard_data = get_wizard_data(request)
    
    # Buscar ferramentas disponíveis para encadeamento
    ferramentas = FerramentaService.listar_todas(db)
    
    return templates.TemplateResponse("ferramenta/wizard/step6.html", {
        "request": request,
        "step_atual": 6,
        "wizard_data": wizard_data,
        "ferramentas": ferramentas
    })


@router.post("/step6")
async def wizard_step6_post(
    request: Request,
    voltar: Optional[str] = Form(None),
    continuar: Optional[str] = Form(None),
    output: str = Form(...),
    channel: Optional[str] = Form(None),
    post_instruction: Optional[str] = Form(None),
    next_tool: Optional[str] = Form(None)
):
    """Processa Step 6."""
    wizard_data = get_wizard_data(request)
    
    if voltar:
        return RedirectResponse(url="/ferramentas/wizard/step5", status_code=303)
    
    if continuar:
        wizard_data.update({
            'output': output,
            'channel': channel,
            'post_instruction': post_instruction,
            'next_tool': next_tool if next_tool else None
        })
        
        save_wizard_data(request, wizard_data)
        return RedirectResponse(url="/ferramentas/wizard/step7", status_code=303)
    
    return RedirectResponse(url="/ferramentas/wizard/step6", status_code=303)


# ==================== STEP 7: Variáveis e Finalização ====================

@router.get("/step7")
async def wizard_step7_get(request: Request):
    """Exibe Step 7 - Resumo Final."""
    wizard_data = get_wizard_data(request)
    
    return templates.TemplateResponse("ferramenta/wizard/step7.html", {
        "request": request,
        "step_atual": 7,
        "wizard_data": wizard_data
    })


@router.post("/step7")
async def wizard_step7_post(
    request: Request,
    db: Session = Depends(get_db),
    voltar: Optional[str] = Form(None),
    finalizar: Optional[str] = Form(None),
    adicionar_variavel: Optional[str] = Form(None),
    remover_variavel: Optional[str] = Form(None),
    var_chave: Optional[str] = Form(None),
    var_valor: Optional[str] = Form(None),
    var_tipo: Optional[str] = Form(None),
    var_descricao: Optional[str] = Form(None),
    var_is_secret: Optional[str] = Form(None)
):
    """Processa Step 7 e finaliza."""
    wizard_data = get_wizard_data(request)
    
    if 'variaveis' not in wizard_data:
        wizard_data['variaveis'] = []
    
    if voltar:
        return RedirectResponse(url="/ferramentas/wizard/step6", status_code=303)
    
    # Adicionar variável
    if adicionar_variavel and var_chave and var_valor:
        wizard_data['variaveis'].append({
            'chave': var_chave,
            'valor': var_valor,
            'tipo': var_tipo or 'secret',
            'descricao': var_descricao or '',
            'is_secret': var_is_secret == 'true'
        })
        save_wizard_data(request, wizard_data)
        return RedirectResponse(url="/ferramentas/wizard/step7", status_code=303)
    
    # Remover variável
    if remover_variavel is not None:
        try:
            idx = int(remover_variavel)
            if 0 <= idx < len(wizard_data['variaveis']):
                wizard_data['variaveis'].pop(idx)
            save_wizard_data(request, wizard_data)
        except:
            pass
        return RedirectResponse(url="/ferramentas/wizard/step7", status_code=303)
    
    # Finalizar - Criar ferramenta
    if finalizar:
        try:
            # Criar ferramenta no banco
            ferramenta_data = FerramentaCriar(
                nome=wizard_data['nome'],
                descricao=wizard_data['descricao'],
                tool_type=ToolType(wizard_data['tool_type']),
                tool_scope=ToolScope(wizard_data['tool_scope']),
                params=json.dumps(wizard_data.get('params', {})),
                curl_command=wizard_data.get('curl_command'),
                codigo_python=wizard_data.get('codigo_python'),
                substituir=wizard_data.get('substituir', True),
                response_map=wizard_data.get('response_map'),
                output=OutputDestination(wizard_data.get('output', 'llm')),
                channel=ChannelType(wizard_data.get('channel', 'text')) if wizard_data.get('channel') else None,
                post_instruction=wizard_data.get('post_instruction'),
                next_tool=wizard_data.get('next_tool'),
                ativa=True
            )
            
            # Criar ferramenta
            nova_ferramenta = FerramentaService.criar(db, ferramenta_data)
            
            # Criar variáveis
            if wizard_data.get('variaveis'):
                for var in wizard_data['variaveis']:
                    FerramentaVariavelService.definir_variaveis_padrao(
                        db, nova_ferramenta.id, {
                            var['chave']: {
                                'valor': var['valor'],
                                'tipo': var['tipo'],
                                'descricao': var['descricao'],
                                'is_secret': var['is_secret']
                            }
                        }
                    )
            
            # Limpar wizard
            clear_wizard_data(request)
            
            return RedirectResponse(url=f"/ferramentas?sucesso=Ferramenta '{nova_ferramenta.nome}' criada com sucesso!", status_code=303)
            
        except Exception as e:
            return templates.TemplateResponse("ferramenta/wizard/step7.html", {
                "request": request,
                "step_atual": 7,
                "wizard_data": wizard_data,
                "erro": f"Erro ao criar ferramenta: {str(e)}"
            })
    
    return RedirectResponse(url="/ferramentas/wizard/step7", status_code=303)
