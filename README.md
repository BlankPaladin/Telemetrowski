# Telemetrovski — Triagem automática de infrações de telemetria

Pipeline em Python que processa relatórios consolidados de telemetria de
frota (PDFs com múltiplos motoristas), separa por motorista, arquiva em
histórico organizado e roteia cada caso para a fila de ação correta com
base na gravidade das violações.

## Problema

Antes da automação, o processo era inteiramente manual: um operador recebia
uma planilha com horários e infrações, gerava um PDF por caso, buscava o
vídeo correspondente, movia os arquivos para a estrutura de pastas correta
(criando as pastas que não existiam) e preenchia um formulário para
registrar cada infração no sistema. Repetido para centenas de páginas por
lote, isso consumia horas de trabalho operacional por semana.

## Solução

O script recebe um ou mais PDFs consolidados (padrão de nome
`rptTelemetriaCaixaPretaMotorista*.pdf`), cada um com múltiplas páginas de
relatório, uma ou mais por motorista.

Fluxo de processamento:

1. **Extração por página**: usa `pypdf` para extrair o texto de cada
   página e regex para identificar CPF, filial, motorista, período
   (dia/mês) e total de violações.
2. **Segmentação em blocos**: páginas consecutivas com o mesmo CPF formam
   um bloco (um caso completo de um motorista).
3. **Tratamento de erro isolado**: se um campo obrigatório não é
   encontrado numa página, o bloco correspondente é extraído para um PDF
   separado (`Filial - Motorista - ERRO.pdf`) e deixado na raiz para
   conferência manual — sem interromper o processamento do restante do
   lote.
4. **Arquivamento histórico**: cada bloco válido é copiado para uma
   estrutura `Mês / Filial / Motorista / Dia / Excesso de Velocidade`,
   pulando a cópia se o arquivo já existir (idempotência entre execuções).
5. **Roteamento por gravidade**: o mesmo PDF é movido para uma fila de
   ação — `1 - fazer e-mail` se o total de violações for baixo, ou
   `2 - requisitar vídeo` se for alto — evitando colisão de nomes com
   arquivos de execuções anteriores.
6. **Limpeza**: o PDF grande original é removido após seu conteúdo ser
   totalmente redistribuído.
7. **Relatório final**: contagem de arquivos processados, enviados a cada
   fila, cópias puladas e blocos com erro.

## Resultado

Processamento de aproximadamente 150 PDFs consolidados em menos de um
minuto, eliminando a triagem manual, erros de arquivamento e
inconsistência de nomenclatura. Próxima fase: integração via API para
requisição automática de vídeo e registro direto da infração no sistema
interno da empresa.

## Stack

Python, `pypdf`, regex, manipulação de sistema de arquivos.

## Configuração

Os caminhos de entrada e destino são lidos de variáveis de ambiente
(`TELEMETROVSKI_PASTA_ORIGEM`, `TELEMETROVSKI_PASTA_DESTINO`), com valores
de exemplo genéricos como fallback — nenhum caminho ou dado interno real
está neste repositório.
