/**
 * ========================================================
 * GOOGLE APPS SCRIPT - Sincronização Mercado Livre (Google Drive)
 * ========================================================
 * 
 * INSTRUÇÕES DE INSTALAÇÃO:
 * 1. Abra sua planilha no Google Sheets.
 * 2. Vá em Extensões > Apps Script.
 * 3. Substitua TODO o código por este.
 * 4. Clique em "Salvar" e "Implantar" > "Nova implantação" (App da Web).
 * 5. Configure: Executar como "Eu", Acesso "Qualquer pessoa".
 * 6. Copie a URL gerada (terminada em /exec) e insira no aplicativo.
 */

function doPost(e) {
  var lock = LockService.getScriptLock();
  lock.tryLock(10000);
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    var data = JSON.parse(e.postData.contents);
    var items = data.products || data;
    if (Array.isArray(items) && items.length > 0) {
      if (sheet.getLastRow() === 0) {
        sheet.appendRow(["Data/Hora", "Loja", "Nome do Produto", "Preço Atual", "Mínimo Histórico", "Nicho"]);
      }
      var rows = items.map(function(item) {
        return [
          item.timestamp || item.data_hora || new Date().toLocaleString("pt-BR"),
          item.loja || "Mercado Livre",
          item.nome || item.title || "",
          item.preco_atual || item.preco || item.price || 0,
          item.minimo_historico || item.menor_preco || item.min_price || 0,
          item.nicho || ""
        ];
      });
      sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
      return ContentService.createTextOutput(JSON.stringify({status: "success", rows: rows.length})).setMimeType(ContentService.MimeType.JSON);
    }
    return ContentService.createTextOutput(JSON.stringify({status: "error", message: "Sem dados válidos"})).setMimeType(ContentService.MimeType.JSON);
  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({status: "error", error: error.toString()})).setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}

function doGet(e) {
  return ContentService
    .createTextOutput(JSON.stringify({
      status: "ok",
      message: "Webhook Mercado Livre Repasse Auto ativo! Use POST para enviar dados.",
      timestamp: new Date().toISOString()
    }))
    .setMimeType(ContentService.MimeType.JSON);
}
