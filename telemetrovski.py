import os
import re
import glob
import shutil
from collections import defaultdict
from pypdf import PdfReader, PdfWriter

# ============================================================
# CONFIGURAÇÕES
#
# Em produção, estes caminhos apontam para pastas internas da
# empresa (ex: um diretório de entrada monitorado e uma estrutura
# de arquivamento histórico compartilhada). Aqui ficam como
# variáveis de ambiente / valores de exemplo para manter o
# repositório livre de qualquer caminho ou dado interno real.
# ============================================================
PASTA_ORIGEM = os.environ.get("TELEMETROVSKI_PASTA_ORIGEM", r"./exemplo/entrada/Telemetrovski")
PASTA_DESTINO = os.environ.get("TELEMETROVSKI_PASTA_DESTINO", r"./exemplo/historico/Infracoes-por-Motorista-x-Dia")

PASTA_EMAIL = os.path.join(PASTA_ORIGEM, "1 - fazer e-mail")
PASTA_VIDEO = os.path.join(PASTA_ORIGEM, "2 - requisitar vídeo")

LIMITE_PICOS = 5  # < 5 -> e-mail | >= 5 -> vídeo

PADRAO_ARQUIVO_ENTRADA = "rptTelemetriaCaixaPretaMotorista*.pdf"

MESES = {
    "01": "01 - Janeiro", "02": "02 - Fevereiro", "03": "03 - Março",
    "04": "04 - Abril",   "05": "05 - Maio",      "06": "06 - Junho",
    "07": "07 - Julho",   "08": "08 - Agosto",    "09": "09 - Setembro",
    "10": "10 - Outubro", "11": "11 - Novembro",  "12": "12 - Dezembro"
}

CARACTERES_INVALIDOS = r'[<>:"/\\|?*]'


def normalizar(texto):
    """Primeira letra de cada palavra maiúscula, resto minúsculo."""
    return " ".join(texto.split()).title()


def sanitizar_nome(texto):
    """Remove caracteres não permitidos em nomes de arquivo/pasta no Windows."""
    return re.sub(CARACTERES_INVALIDOS, "", texto).strip()


def extrair_info_pagina(texto_pagina):
    """
    Extrai os campos de uma única página (cabeçalho se repete em todas).
    Retorna dict com cpf, filial, motorista, mes, dia, picos, erro.
    """
    resultado = {
        "cpf": None, "filial": None, "motorista": None,
        "mes": None, "dia": None, "picos": None, "erro": None,
    }

    if not texto_pagina or not texto_pagina.strip():
        resultado["erro"] = "Página sem texto extraível (possivelmente corrompida ou digitalizada como imagem)."
        return resultado

    cpf_match = re.search(r"CPF:\s*([\d\.\-]+)", texto_pagina)
    if not cpf_match:
        resultado["erro"] = "Campo 'CPF:' não encontrado na página."
        return resultado
    resultado["cpf"] = re.sub(r"\D", "", cpf_match.group(1))

    motorista_match = re.search(r"Motorista:\s*(.*?)\s*Placa:", texto_pagina, re.DOTALL)
    if not motorista_match:
        resultado["erro"] = "Campo 'Motorista:' não encontrado na página."
        return resultado

    motorista_completo = " ".join(motorista_match.group(1).split())
    if " - " in motorista_completo:
        partes = motorista_completo.split(" - ", 1)
        filial = normalizar(partes[0])
        nome_motorista = normalizar(partes[1])
    else:
        filial = "Sem Filial"
        nome_motorista = normalizar(motorista_completo)

    resultado["filial"] = sanitizar_nome(filial)
    resultado["motorista"] = sanitizar_nome(nome_motorista)

    periodo_match = re.search(r"Período:\s+(\d{2})/(\d{2})/(\d{4})", texto_pagina)
    if not periodo_match:
        resultado["erro"] = "Campo 'Período:' não encontrado na página."
        return resultado
    resultado["dia"] = periodo_match.group(1)
    resultado["mes"] = periodo_match.group(2)

    picos_match = re.search(r"Total Violações:\s*(\d+)(?!\s*da)", texto_pagina)
    if not picos_match:
        resultado["erro"] = "Campo 'Total Violações:' não encontrado na página."
        return resultado
    resultado["picos"] = int(picos_match.group(1))

    return resultado


def proximo_nome_disponivel(pasta, nome_base_sem_extensao, extensao=".pdf", numero_inicial=1):
    numero = numero_inicial
    while True:
        nome = f"{nome_base_sem_extensao} {numero}{extensao}"
        caminho = os.path.join(pasta, nome)
        if not os.path.exists(caminho):
            return nome, caminho
        numero += 1


def dividir_em_blocos(caminho_pdf_grande):
    """
    Lê o PDF grande página a página e agrupa páginas consecutivas do mesmo
    CPF em blocos. Retorna uma lista de blocos, cada um:
    {'paginas': [indices], 'cpf':.., 'filial':.., 'motorista':.., 'mes':.., 'dia':.., 'picos':.., 'erro': str|None}
    """
    reader = PdfReader(caminho_pdf_grande)
    total_paginas = len(reader.pages)

    blocos = []
    bloco_atual = None  # dict

    for i in range(total_paginas):
        try:
            texto_pagina = reader.pages[i].extract_text()
        except Exception as e:
            texto_pagina = None
            erro_extracao = f"Erro ao ler a página: {e}"
        else:
            erro_extracao = None

        if erro_extracao:
            info = {"erro": erro_extracao}
        else:
            info = extrair_info_pagina(texto_pagina)

        if info["erro"]:
            motivo = f"{info['erro']} (página {i + 1} do arquivo original)"
            if bloco_atual is not None:
                # a página com erro pertence ao bloco em andamento
                bloco_atual["paginas"].append(i)
                bloco_atual["erro"] = motivo
                blocos.append(bloco_atual)
            else:
                blocos.append({
                    "paginas": [i], "cpf": None, "filial": None, "motorista": None,
                    "mes": None, "dia": None, "picos": None, "erro": motivo,
                })
            bloco_atual = None
            continue

        if bloco_atual is not None and info["cpf"] == bloco_atual["cpf"]:
            bloco_atual["paginas"].append(i)
        else:
            if bloco_atual is not None:
                blocos.append(bloco_atual)
            bloco_atual = {
                "paginas": [i],
                "cpf": info["cpf"], "filial": info["filial"], "motorista": info["motorista"],
                "mes": info["mes"], "dia": info["dia"], "picos": info["picos"],
                "erro": None,
            }

    if bloco_atual is not None:
        blocos.append(bloco_atual)

    return blocos, total_paginas


def escrever_paginas(caminho_pdf_grande, indices_paginas, caminho_saida):
    reader = PdfReader(caminho_pdf_grande)
    writer = PdfWriter()
    for i in indices_paginas:
        writer.add_page(reader.pages[i])
    with open(caminho_saida, "wb") as f:
        writer.write(f)


def processar():
    os.makedirs(PASTA_EMAIL, exist_ok=True)
    os.makedirs(PASTA_VIDEO, exist_ok=True)

    arquivos_grandes = sorted(glob.glob(os.path.join(PASTA_ORIGEM, PADRAO_ARQUIVO_ENTRADA)))

    if not arquivos_grandes:
        print(f"Nenhum arquivo '{PADRAO_ARQUIVO_ENTRADA}' encontrado na pasta de origem.")
        return

    contador_nomes = defaultdict(int)  # chave: (filial, motorista) -> contador
    contador_erros = defaultdict(int)  # chave: (filial, motorista) -> contador de blocos de erro

    enviados_email = []
    enviados_video = []
    pulados_destino_existente = []
    blocos_com_erro = []

    for caminho_pdf_grande in arquivos_grandes:
        nome_arquivo_grande = os.path.basename(caminho_pdf_grande)
        print(f"Lendo '{nome_arquivo_grande}'...")

        blocos, total_paginas = dividir_em_blocos(caminho_pdf_grande)
        print(f"{total_paginas} página(s) lida(s), {len(blocos)} bloco(s) identificado(s).\n")

        for bloco in blocos:
            primeira_pagina = bloco["paginas"][0] + 1
            ultima_pagina = bloco["paginas"][-1] + 1

            if bloco["erro"]:
                # --- Bloco com erro: extrai as páginas e deixa na raiz ---
                if bloco["motorista"]:
                    chave_erro = (bloco["filial"], bloco["motorista"])
                    contador_erros[chave_erro] += 1
                    sufixo = "" if contador_erros[chave_erro] == 1 else f" {contador_erros[chave_erro]}"
                    nome_erro = sanitizar_nome(f"{bloco['filial']} - {bloco['motorista']} - ERRO{sufixo}.pdf")
                else:
                    nome_erro = f"Erro - Paginas {primeira_pagina} a {ultima_pagina}.pdf"

                caminho_erro = os.path.join(PASTA_ORIGEM, nome_erro)
                # evita sobrescrever um erro anterior com o mesmo nome
                base_sem_ext = os.path.splitext(nome_erro)[0]
                if os.path.exists(caminho_erro):
                    nome_erro, caminho_erro = proximo_nome_disponivel(PASTA_ORIGEM, base_sem_ext, numero_inicial=2)

                escrever_paginas(caminho_pdf_grande, bloco["paginas"], caminho_erro)
                blocos_com_erro.append((nome_erro, bloco["erro"]))
                print(f"[ERRO] Páginas {primeira_pagina} a {ultima_pagina} -> '{nome_erro}'")
                print(f"       Motivo: {bloco['erro']}\n")
                continue

            # --- Bloco válido ---
            filial = bloco["filial"]
            motorista = bloco["motorista"]
            mes = bloco["mes"]
            dia = bloco["dia"]
            picos = bloco["picos"]

            try:
                chave_nome = (filial, motorista)
                contador_nomes[chave_nome] += 1

                nome_base = f"{filial} - {motorista}"
                novo_nome, novo_caminho_origem = proximo_nome_disponivel(
                    PASTA_ORIGEM, nome_base, numero_inicial=contador_nomes[chave_nome]
                )
                match_num = re.search(r'(\d+)\.pdf$', novo_nome)
                if match_num:
                    contador_nomes[chave_nome] = int(match_num.group(1))

                escrever_paginas(caminho_pdf_grande, bloco["paginas"], novo_caminho_origem)
                print(f"Extraído: páginas {primeira_pagina}-{ultima_pagina} ({motorista}, {dia}/{mes}) -> {novo_nome}")

                # --- Copiar para o histórico organizado ---
                pasta_mes = MESES.get(mes, f"{mes} - Mês")
                destino = os.path.join(
                    PASTA_DESTINO, pasta_mes, filial, motorista, dia, "Excesso de Velocidade"
                )
                os.makedirs(destino, exist_ok=True)
                destino_arquivo = os.path.join(destino, novo_nome)

                if os.path.exists(destino_arquivo):
                    pulados_destino_existente.append(novo_nome)
                    print(f"   -> Já existe no histórico organizado, cópia pulada.")
                else:
                    shutil.copy2(novo_caminho_origem, destino_arquivo)
                    print(f"   -> Copiado para o histórico: {pasta_mes} \\ {filial} \\ {motorista} \\ {dia} \\ Excesso de Velocidade")

                # --- Mover para a fila de ação ---
                pasta_acao = PASTA_EMAIL if picos < LIMITE_PICOS else PASTA_VIDEO
                nome_fila = "1 - fazer e-mail" if picos < LIMITE_PICOS else "2 - requisitar vídeo"
                destino_acao = os.path.join(pasta_acao, novo_nome)

                if os.path.exists(destino_acao):
                    motivo = (
                        f"{picos} pico(s) -> deveria ir para '{nome_fila}', mas já existe um arquivo "
                        f"com o nome '{novo_nome}' lá (provavelmente de uma execução anterior). "
                        f"Arquivo mantido em Telemetrovski para conferência manual."
                    )
                    blocos_com_erro.append((novo_nome, motivo))
                    print(f"   -> [ERRO] {motivo}\n")
                    continue

                shutil.move(novo_caminho_origem, destino_acao)
                if picos < LIMITE_PICOS:
                    enviados_email.append((novo_nome, picos))
                else:
                    enviados_video.append((novo_nome, picos))
                print(f"   -> {picos} pico(s) -> movido para '{nome_fila}'\n")

            except Exception as e:
                blocos_com_erro.append((f"páginas {primeira_pagina}-{ultima_pagina}", f"Erro inesperado: {e}"))
                print(f"[ERRO] Bloco páginas {primeira_pagina}-{ultima_pagina}\n       -> Erro inesperado: {e}\n")

        # --- Exclui o PDF grande original, já totalmente redistribuído ---
        os.remove(caminho_pdf_grande)
        print(f"Arquivo original '{nome_arquivo_grande}' excluído (conteúdo já redistribuído).\n")

    # --- Relatório final ---
    print("\n" + "=" * 60)
    print("RELATÓRIO FINAL")
    print("=" * 60)
    print(f"Arquivo(s) de origem processado(s): {len(arquivos_grandes)}")
    print(f"Enviados para '1 - fazer e-mail': {len(enviados_email)}")
    print(f"Enviados para '2 - requisitar vídeo': {len(enviados_video)}")
    print(f"Cópias puladas no histórico (já existiam): {len(pulados_destino_existente)}")
    print(f"Blocos com erro (arquivo retido em Telemetrovski): {len(blocos_com_erro)}")

    if enviados_email:
        print("\n--- Fila: 1 - fazer e-mail ---")
        for nome, picos in enviados_email:
            print(f"   - {nome} ({picos} picos)")

    if enviados_video:
        print("\n--- Fila: 2 - requisitar vídeo ---")
        for nome, picos in enviados_video:
            print(f"   - {nome} ({picos} picos)")

    if pulados_destino_existente:
        print("\n--- Cópias puladas no histórico (já existiam) ---")
        for p in pulados_destino_existente:
            print(f"   - {p}")

    if blocos_com_erro:
        print("\n--- Blocos com erro (arquivo retido em Telemetrovski) ---")
        for nome, motivo in blocos_com_erro:
            print(f"   - {nome}\n     Motivo: {motivo}")

    print("\nProcesso concluído.")


if __name__ == "__main__":
    processar()
