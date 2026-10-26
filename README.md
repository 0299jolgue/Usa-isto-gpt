# Brawl Room: várias contas e telemóveis

O site controla vários agentes Python, um por LDPhone. Cada agente usa a conta aberta na aplicação oficial e recebe ações individuais ou para todos os telemóveis ligados.

## Servidor

Importa este repositório para a ShardCloud. `main.py` inicia Flask com Waitress em `0.0.0.0` na porta indicada por `PORT`, ou 80. A página inicial redireciona para `/bridge`.

## Instalação no LDPhone

Entra no painel, copia o comando de ligação e executa-o no Termux de cada LDPhone. O comando inclui um código de emparelhamento válido por dez minutos. Os agentes antigos precisam de ser atualizados e emparelhados após esta versão.

O painel oferece entrar numa sala, iniciar partida, testar a IA e tirar prints, por telemóvel ou para todos os ligados. Cada dispositivo tem nome, tag do jogador, estado e última captura.

## Login e dados

O utilizador inicial é `jolgue`; a senha fornecida pelo proprietário está guardada como hash. `PANEL_USERNAME`, `PANEL_PASSWORD` e `PANEL_SESSION_SECRET` permitem trocar as credenciais por variáveis de ambiente. Dispositivos, tags, capturas e chave da API ficam em SQLite sob `BRAWL_STATE_DIR` (`/tmp/brawl-room-data` por omissão). Para persistirem entre reinstalações da ShardCloud, configura essa variável para um volume persistente.

## Troféus

Para mostrar os troféus de cada conta, guarda a tag do jogador no respetivo cartão e uma chave da API oficial no painel. A chave tem de autorizar o IP de saída da ShardCloud. O painel consulta `GET /v1/players/%23TAG` e mantém o número até à próxima atualização. Prints e controlo não precisam dessa chave.

## Teste da IA

O botão **Testar IA durante 20 segundos** abre o jogo, tenta iniciar uma partida e depois processa capturas do LDPhone no servidor. O modelo ONNX de deteção de jogadores do [PylaAI](https://github.com/PylaAI/PylaAI) é descarregado do commit `284714d` na primeira utilização, verificado por SHA-256 e mantido fora do repositório deste site. O modelo e a lógica de decisão correm na ShardCloud; o agente envia as capturas e executa gestos de joystick no jogo. O teste regista o tempo de cada ciclo no Termux e apresenta mediana e P90 no site.

Esta é uma primeira política de ataque ao inimigo mais próximo e movimento até ao centro quando não encontra inimigos. O jogo tem de estar no ecrã do LDPhone. A meta de 0,5 segundo por ciclo só pode ser validada com os tempos reais do LDPhone e da ShardCloud. O modelo original do PylaAI é distribuído sob CC BY-NC 4.0; o metadata ONNX também declara AGPL-3.0 para Ultralytics.

## Testes

Arranque, fila, consulta pelo agente, abertura simulada do convite, atualização de estado e inferência ONNX sobre uma imagem sintética foram testados localmente. A entrada real e o ciclo de jogo dependem do teste no LDPhone.


## Controlo do jogo

No LDPhone, instala OCR com `pkg install -y tesseract` e reinicia o agente usando o comando atualizado no painel. O botão de troféus tira um novo print; o agente tenta reconhecer o número da zona do perfil e envia-o ao painel. Esta leitura depende do layout mostrado no ecrã.

Para trocar de brawler, abre o print da conta e toca no ponto desejado. O agente converte o ponto à resolução do LDPhone, toca no jogo e tira outro print. Repete até selecionar o brawler.

O auto farm inicia partidas e aplica a IA existente em ciclos; o botão Parar interrompe o ciclo seguinte. Mantém a página do trabalho aberta para ver o estado.
