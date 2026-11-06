import os
import time
import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai

# --- SUAS CHAVES ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

def extrair_itens_da_imagem(caminho_imagem):
    imagem = Image.open(caminho_imagem)
    prompt = (
        "Analise esta imagem da minha lista de compras. "
        "Retorne APENAS uma lista simples de produtos limpos, um por linha, "
        "sem numeração ou hífens. Exemplo:\nFarinha de trigo\nLeite condensado\nGordura vegetal"
    )
    resposta = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[imagem, prompt]
    )
    itens = [item.strip() for item in resposta.text.split("\n") if item.strip()]
    return itens

def buscar_preco_item(termo_busca, latitude=-7.115, longitude=-34.863):
    url = "https://precodahora.pb.gov.br/api/v1/produtos"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "termo": termo_busca,
        "latitude": latitude,
        "longitude": longitude,
        "raio": 15,
        "pagina": 1,
        "ordenar": "preco.asc"
    }
    
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))

    try:
        time.sleep(1)
        resposta = session.post(url, json=payload, headers=headers, timeout=15)
        
        if resposta.status_code == 200:
            dados = resposta.json()
            if dados.get("resultado"):
                melhor_opcao = dados["resultado"][0]
                return {
                    "produto": melhor_opcao.get("descricao"),
                    "preco": melhor_opcao.get("preco"),
                    "estabelecimento": melhor_opcao.get("estabelecimento", {}).get("nomeFantasia", "Mercado Local"),
                    "bairro": melhor_opcao.get("estabelecimento", {}).get("bairro", "JP")
                }
    except Exception as e:
        print(f"Erro ao buscar {termo_busca}: {e}")
    return None

async def processar_lista_itens(update: Update, itens: list):
    if not itens:
        await update.message.reply_text("Não foi possível identificar os produtos. Tente enviar novamente.")
        return

    mensagem_retorno = f"📝 **Itens identificados:**\n" + "\n".join([f"• {i}" for i in itens]) + "\n\n🔍 **Menores preços encontrados:**\n\n"
    
    total_estimado = 0.0
    mercados_contagem = {}

    for item in itens:
        resultado = buscar_preco_item(item)
        if resultado:
            preco = resultado['preco']
            total_estimado += preco
            estabelecimento = resultado['estabelecimento']
            mercados_contagem[estabelecimento] = mercados_contagem.get(estabelecimento, 0) + 1
            
            mensagem_retorno += (
                f"✅ **{item.title()}**\n"
                f"└ R$ {preco:.2f} — *{estabelecimento}* ({resultado['bairro']})\n"
            )
        else:
            mensagem_retorno += f"❌ **{item.title()}**: Não encontrado na base recente.\n"

    mercado_mais_barato = max(mercados_contagem, key=mercados_contagem.get) if mercados_contagem else "N/A"
    
    mensagem_retorno += f"\n💰 **Valor total estimado:** R$ {total_estimado:.2f}\n"
    mensagem_retorno += f"🏪 **Recomendação principal:** O local com maior concentração de itens baratos é o **{mercado_mais_barato}**."
    
    await update.message.reply_text(mensagem_retorno, parse_mode="Markdown")

async def processar_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Foto recebida! A extrair os itens da lista e a consultar os menores preços em João Pessoa...")
    foto_file = await update.message.photo[-1].get_file()
    caminho_foto = "lista_temp.jpg"
    await foto_file.download_to_drive(caminho_foto)
    
    itens = extrair_itens_da_imagem(caminho_foto)
    if os.path.exists(caminho_foto):
        os.remove(caminho_foto)
        
    await processar_lista_itens(update, itens)

async def processar_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if texto.startswith("/"):
        return
        
    await update.message.reply_text("💬 Lista de texto recebida! A pesquisar os menores preços em João Pessoa...")
    if "\n" in texto:
        itens = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    else:
        itens = [item.strip() for item in texto.split(",") if item.strip()]
        
    await processar_lista_itens(update, itens)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Olá! Envie uma foto da sua lista ou digite os produtos por texto (um por linha ou separados por vírgula) "
        "para eu pesquisar os menores preços nos supermercados de João Pessoa!"
    )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, processar_foto))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, processar_texto))
    
    print("🤖 Bot rodando na nuvem 24h!")
    app.run_polling()
