import subprocess
import sys

def instalar_bibliotecas():
    # Lista de dependências necessárias para o Cérebro de Engenharia
    bibliotecas = [
        "yake",           # Extração de palavras-chave
        "python-docx",    # Processamento de arquivos Word
        "pypdf",          # Processamento de arquivos PDF
        "openpyxl",       # Geração de planilhas Excel
        "google-genai",        # Motor de IA Gemini (SDK novo — substitui google-generativeai)
        "python-dotenv",  # Gerenciamento de chaves de API (.env)
        "pyyaml"          # Leitura de configurações
    ]

    print("🚀 Iniciando a instalação das dependências do sistema...")
    print("-" * 50)

    for lib in bibliotecas:
        print(f"📦 Tentando instalar: {lib}...")
        try:
            # Chama o pip através do executável atual do Python para evitar erros de PATH
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib])
            print(f"✅ {lib} instalada com sucesso!\n")
        except Exception as e:
            print(f"❌ Erro ao instalar {lib}: {e}\n")

    print("-" * 50)
    print("🏁 Processo finalizado! Agora tente rodar o sistema novamente.")

if __name__ == "__main__":
    instalar_bibliotecas()