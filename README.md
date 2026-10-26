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

O auto farm corre um ciclo contínuo: usa templates de estado do PylaAI fixados no commit `284714d` para identificar lobby, procura de partida e fim de jogo; inicia/avança os ecrãs correspondentes e aplica o modelo ONNX nas partidas. O botão Parar é verificado a cada poucos segundos. Os templates são descarregados e guardados na primeira utilização. A política de movimento/ataque é uma adaptação simplificada do projeto PylaAI; a validação final exige observar uma partida real no LDPhone.


No LDPhone com root, o agente usa os eventos multitouch do Android para manter o joystick pressionado entre imagens e disparar com um segundo dedo. Ao parar, sair do combate ou ocorrer um erro, solta ambos os toques. Se o dispositivo não expuser um ecrã multitouch acessível por root, o agente regista a falha no Termux e usa gestos longos como recurso alternativo.

## Menu flutuante no LDPhone

O projeto `android-overlay/` compila uma app Android externa. O APK para instalar está na release `overlay-v1`: https://github.com/0299jolgue/Usa-isto-gpt/releases/download/overlay-v1/brawl-room-menu.apk. O workflow **Build Android overlay** também guarda o APK no artefacto `brawl-room-menu-apk` da página **Actions** do GitHub. No LDPhone, instala o APK, abre **Brawl Room Menu**, introduz o endereço HTTPS do teu site, concede a permissão **Mostrar sobre outras aplicações** e carrega em **Abrir menu**. Toca na bolha ✳ para expandir, usa **Iniciar auto farm** ou **Parar seleção**, e fecha no ✕. O menu mostra as estatísticas de aprendizagem recebidas do agente.

O agente escolhe entre as táticas `aggressive`, `balanced` e `cautious` por amostragem de resultados. Depois de uma vitória ou derrota observada, guarda os totais no ficheiro privado `~/.brawl_room_tactics.json` do Termux e envia um resumo ao painel. Partidas sem resultado reconhecido não alteram a escolha. Isto adapta a seleção entre três políticas; não treina um novo modelo de visão nem garante melhoria em cada partida.

Durante a partida, a política estima a vida pela barra verde do jogador. Uma perda repentina de vida provoca uma esquiva curta; com vida baixa e espaço para recuar, suspende o ataque para permitir regeneração. No ecrã inicial o agente lê «Combate»/«Showdown» e, nesse modo, procura caixas pela cor, forma e barra de vida; aproxima-se antes de atacar, especialmente se reconhecer Shelly. O Termux regista `tática` e `vida` em cada ciclo. Estas heurísticas dependem da aparência atual do jogo e ainda precisam de validação em capturas reais do LDPhone.
