import threading
import time
import os
import random
import urllib.request
import urllib.error
import json
from datetime import datetime
import database as db
import niche_scraper as scraper
from oferta import publicar_oferta

def _post_json_with_redirects(url: str, payload_dict: dict, timeout: int = 30) -> tuple[int, str]:
    """Envia POST JSON com suporte a redirecionamentos via requests (se instalado) ou urllib como fallback."""
    try:
        import requests
        res = requests.post(
            url,
            json=payload_dict,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
            timeout=timeout
        )
        return res.status_code, res.text
    except Exception:
        import urllib.request
        import json
        json_bytes = json.dumps(payload_dict).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=json_bytes,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST"
        )
        class SmartRedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if code in (301, 302, 303, 307, 308):
                    return urllib.request.Request(
                        newurl,
                        data=req.data if code in (307, 308) else None,
                        headers=req.headers,
                        method="POST" if code in (307, 308) else "GET"
                    )
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        opener = urllib.request.build_opener(SmartRedirectHandler())
        with opener.open(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="ignore")


def sync_to_google_sheets(webhook_url: str) -> tuple:
    """Envia a lista de produtos de nicho ativos para a planilha do Google Drive via Apps Script Webapp com suporte a redirecionamentos (302/307)."""
    import re as _re

    try:
        if "docs.google.com/spreadsheets" in webhook_url:
            msg = "Você inseriu a URL direta da planilha! Precisa usar a URL do Web App gerada no Apps Script (que termina com /exec)."
            print(f"[Sheets Sync] [ERRO] {msg}")
            return False, msg

        if "/exec" not in webhook_url and "/dev" not in webhook_url:
            msg = "A URL do Webhook não parece ser um deploy válido do Apps Script. Ela deve terminar em /exec."
            print(f"[Sheets Sync] [AVISO] {msg}")
            return False, msg

        if "/dev" in webhook_url:
            msg = "Você está usando a URL de desenvolvimento (/dev). Use a URL de produção (/exec) nas configurações."
            print(f"[Sheets Sync] [AVISO] {msg}")
            return False, msg

        products = db.listar_produtos_nicho(nicho="Todos os Nichos", limit=300)
        if not products:
            msg = "Nenhum produto cadastrado nos nichos para sincronizar."
            print(f"[Sheets Sync] {msg}")
            return False, msg

        safe_products = []
        agora_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        for p in products:
            safe_products.append({
                "timestamp": agora_str,
                "loja": str(p.get("marketplace") or "Mercado Livre"),
                "nome": str(p.get("nome", "")),
                "preco_atual": float(p.get("preco_atual") or 0),
                "minimo_historico": float(p.get("menor_preco") or 0),
                "nicho": str(p.get("nicho", ""))
            })

        payload = {"products": safe_products}
        print(f"[Sheets Sync] Enviando {len(safe_products)} produtos via POST (allow_redirects=True)...")
        
        status_code, res_body = _post_json_with_redirects(webhook_url, payload, timeout=30)
        res_body = res_body.strip()
        print(f"[Sheets Sync] HTTP {status_code} | Resposta: {res_body[:200]}")
        
        if res_body.startswith("<!DOCTYPE") or "<html" in res_body[:100].lower():
            title_match = _re.search(r'<title>(.*?)</title>', res_body)
            title = title_match.group(1) if title_match else "Erro desconhecido"
            msg = f"Google Apps Script retornou HTML de erro: '{title}'"
            print(f"[Sheets Sync] [ERRO] {msg}")
            return False, msg
            
        try:
            res_data = json.loads(res_body)
            if res_data.get("status") == "success":
                rows = res_data.get("rows", len(safe_products))
                msg = f"Sincronização concluída com sucesso! {rows} linhas atualizadas."
                print(f"[Sheets Sync] [OK] {msg}")
                return True, msg
            else:
                err_msg = res_data.get("message") or res_data.get("error", "Erro ao processar dados no Google Apps Script.")
                msg = f"Resposta do script: {err_msg}"
                print(f"[Sheets Sync] [AVISO] {msg}")
                return False, msg
        except Exception:
            if "success" in res_body.lower():
                msg = "Sincronização concluída!"
                return True, msg
            return False, f"Resposta não-JSON do servidor: {res_body[:150]}"

    except Exception as e:
        err_msg = f"Erro inesperado: {e}"
        print(f"[Sheets Sync] [ERRO] {err_msg}")
        return False, err_msg


def log_disparo_to_google_sheets(webhook_url: str, conta: str, destinatario: str, status: str, detalhes: str = ""):
    """Envia o log de execução do Disparador diretamente para o Google Sheets via POST com redirecionamento."""
    if not webhook_url or "/exec" not in webhook_url:
        return
        
    def _do_post():
        try:
            log_item = {
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "loja": "Mercado Livre",
                "nome": f"[Disparo Telegram: {status}] {detalhes[:100]}",
                "preco_atual": 0.0,
                "minimo_historico": 0.0,
                "nicho": f"Conta: {conta} | Destino: {destinatario}"
            }
            log_payload = {"products": [log_item]}
            _post_json_with_redirects(webhook_url, log_payload, timeout=15)
        except Exception as e:
            print(f"[Sheets Log Disparo] Erro ao enviar log: {e}")

    t = threading.Thread(target=_do_post, daemon=True)
    t.start()


def gerar_url_afiliada_produto(p: dict) -> str:
    """Aplica a tag/cookie de afiliado configurada no banco de dados no link original."""
    from affiliate_helper import update_amazon_url, update_shopee_url, update_mercadolivre_url, update_magalu_url
    
    marketplace = p["marketplace"].lower().replace(" ", "")
    original_url = p["url_original"]
    
    integrations = db.listar_integracoes()
    tag = ""
    cookie = ""
    for i in integrations:
        if i["tipo"] == marketplace and i.get("ativo", 1):
            tag = i.get("tag", "")
            cookie = i.get("cookie", "")
            break
            
    if not tag:
        return original_url
        
    try:
        if marketplace == "amazon":
            return update_amazon_url(original_url, tag)
        elif marketplace == "shopee":
            return update_shopee_url(original_url, tag)
        elif marketplace == "mercadolivre":
            return update_mercadolivre_url(original_url, tag, cookie)
        elif marketplace == "magalu":
            return update_magalu_url(original_url, tag)
        elif marketplace == "aliexpress":
            if "?" in original_url:
                return f"{original_url}&dl_target_url={tag}"
            else:
                return f"{original_url}?dl_target_url={tag}"
    except Exception:
        pass
    return original_url

class NicheScheduler:
    def __init__(self):
        self.thread = None
        self.running = False
        self.log_callback = None
        self.last_status = "Inativo"
        self.error_logs = []

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.last_status = "Ativo (Aguardando horário)"

    def stop(self):
        self.running = False
        self.last_status = "Inativo"

    def _loop(self):
        while self.running:
            try:
                ativo = db.get_config("nicho_scheduler_ativo", "0")
                if db.get_config("pausado", "0") == "1":
                    self.last_status = "Pausado (painel do bot)"
                elif ativo == "1":
                    self.last_status = "Ativo (Aguardando horário)"
                    hora_post = db.get_config("nicho_scheduler_hora", "09:00")
                    ultimo_dia = db.get_config("nicho_scheduler_ultimo_dia_rodado", "")
                    
                    agora = datetime.now()
                    hoje_str = agora.strftime("%Y-%m-%d")
                    hora_str = agora.strftime("%H:%M")
                    
                    if hoje_str != ultimo_dia and hora_str >= hora_post:
                        self._log("⏰ Horário agendado detectado! Iniciando rotina diária...")
                        db.set_config("nicho_scheduler_ultimo_dia_rodado", hoje_str)
                        self.executar_rotina_completa()
                else:
                    self.last_status = "Inativo"
            except Exception as e:
                self._log(f"❌ Erro crítico no loop do agendador: {e}")
                
            time.sleep(30) # verifica a cada 30 segundos

    def _log(self, text: str):
        msg = f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {text}"
        print(msg)
        if self.log_callback:
            try:
                self.log_callback(msg)
            except Exception:
                pass
        self.error_logs.append(msg)
        if len(self.error_logs) > 100:
            self.error_logs.pop(0)

    def executar_rotina_completa(self) -> bool:
        self.last_status = "Executando..."
        self._log("🔍 1. Buscando novos produtos nos nichos...")
        
        try:
            scraper.executar_busca_diaria(progress_callback=self._log)
        except Exception as e:
            self._log(f"❌ Erro ao buscar produtos: {e}")
            db.salvar_disparo_status(None, datetime.now().strftime("%Y-%m-%d"), "falha", f"Scraper: {str(e)}")
            self.last_status = "Falha no Scraper"
            return False

        webhook = db.get_config("nicho_scheduler_sheets_webhook", "")
        if webhook:
            self._log("📊 2. Sincronizando produtos com Google Sheets...")
            sync_ok, sync_msg = sync_to_google_sheets(webhook)
            if sync_ok:
                self._log(f"✅ Sincronização com Google Sheets: {sync_msg}")
            else:
                self._log(f"⚠️ Falha ao sincronizar com Google Sheets: {sync_msg}")

        self._log("✈️ 3. Processando e disparando ofertas no Telegram...")
        
        conta_id_str = db.get_config("nicho_scheduler_conta", "")
        destino = db.get_config("nicho_scheduler_destino", "")
        
        if not conta_id_str or not destino:
            self._log("⚠️ Conta ou canal de destino não configurados. Disparo cancelado.")
            db.salvar_disparo_status(None, datetime.now().strftime("%Y-%m-%d"), "falha", "Configurações ausentes: Conta remetente ou canal de destino.")
            self.last_status = "Configurações ausentes"
            return False
            
        try:
            conta_id = int(conta_id_str)
        except ValueError:
            self._log("❌ Conta configurada inválida.")
            self.last_status = "Erro: Conta inválida"
            return False

        # Só publica o que foi coletado hoje: evita repostar preço velho (ou dado antigo do fallback removido)
        hoje = datetime.now().strftime("%Y-%m-%d")
        produtos = [p for p in db.listar_produtos_nicho(order_by="desconto", limit=100)
                    if p["ultima_atualizacao"] == hoje][:10]
        if not produtos:
            self._log("⚠️ Nenhum produto encontrado para postagem.")
            self.last_status = "Concluído (Nenhuma oferta)"
            return True
            
        from telegram_manager import telegram_manager
        if not telegram_manager.via_bot() and not telegram_manager.clients.get(conta_id):
            err_msg = "Bot não configurado e conta remetente offline. Configure o bot ou conecte a conta!"
            self._log(f"❌ {err_msg}")
            db.salvar_disparo_status(None, datetime.now().strftime("%Y-%m-%d"), "falha", err_msg)
            self.last_status = "Falha: Conta offline"
            return False
            
        hoje_data = datetime.now().strftime("%Y-%m-%d")
        sucessos = 0
        
        for idx, p in enumerate(produtos, 1):
            try:
                aff_url = gerar_url_afiliada_produto(p)
                p["url_afiliado"] = aff_url
                db.salvar_produto_nicho(p)
                publicar_oferta(p, conta_id, destino)
                db.salvar_disparo_status(p["id"], hoje_data, "enviado")
                self._log(f"✅ Oferta [{idx}/{len(produtos)}] enviada: {p['nome'][:30]}...")
                sucessos += 1
                
                time.sleep(random.randint(10, 20))
            except Exception as item_err:
                self._log(f"❌ Falha ao enviar produto {p['id']}: {item_err}")
                db.salvar_disparo_status(p["id"], hoje_data, "falha", str(item_err))
                
        self._log(f"🏁 Rotina diária concluída! {sucessos} de {len(produtos)} ofertas postadas com sucesso.")
        self.last_status = "Ativo (Aguardando horário)" if sucessos > 0 else "Falhou"
        return True

# Singleton Global
niche_scheduler = NicheScheduler()
