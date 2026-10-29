# Brawl Room: várias contas e telemóveis

O site controla vários agentes Python, um por LDPhone. Cada agente usa a conta aberta na aplicação oficial e recebe ações individuais ou para todos os telemóveis ligados.

## Servidor

Importa este repositório para a ShardCloud. `main.py` inicia Flask com Waitress em `0.0.0.0` na porta indicada por `PORT`, ou 80. A página inicial redireciona para `/bridge`.

## Instalação no LDPhone

Entra no painel, copia o comando de ligação e executa-o no Termux de cada LDPhone. O código de emparelhamento mantém-se estável enquanto a senha do painel não mudar. Atualiza o ficheiro do agente e reinicia-o para receber funções novas.

O painel oferece entrar numa sala, iniciar partida, testar a IA e tirar prints, por telemóvel ou para todos os ligados. Cada dispositivo tem nome, tag do jogador, estado e última captura.

## Login e dados

O utilizador inicial é `jolgue`; a senha fornecida pelo proprietário está guardada como hash. `PANEL_USERNAME`, `PANEL_PASSWORD` e `PANEL_SESSION_SECRET` permitem trocar as credenciais por variáveis de ambiente. Dispositivos, tags, capturas e chave da API ficam em SQLite sob `BRAWL_STATE_DIR` (`/tmp/brawl-room-data` por omissão). Para persistirem entre reinstalações da ShardCloud, configura essa variável para um volume persistente.

## Troféus

O botão **Troféus** pede ao LDPhone um print do lobby e tenta ler o total por OCR. A conta deve estar no lobby; um número que o OCR não consiga confirmar fica por atualizar. A tag no cartão identifica a conta para o operador.

## Painel novo

O painel usa uma seleção de conta para todos os comandos e guarda a escolha no navegador. Mostra números de telemóveis ligados, farms ativos, ações em fila e contas com Ranked confirmado. Cada cartão mostra o último sinal, a fila, o progresso enviado pelo agente durante o farm e a captura mais recente. A lista pode mostrar só telemóveis ligados. O botão **Atualizar ecrã** pede um novo print; **Limpar fila** cancela ações ainda não iniciadas; **Parar auto farm** envia uma paragem para a conta escolhida ou para todas. O histórico guarda as últimas 250 transições em SQLite e mostra as 12 mais recentes no painel. O navegador atualiza estado e histórico a cada cinco segundos.

## Teste da IA

O botão **Testar IA durante 20 segundos** abre o jogo, tenta iniciar uma partida e depois processa capturas do LDPhone no servidor. O modelo ONNX de deteção de jogadores do [PylaAI](https://github.com/PylaAI/PylaAI) é descarregado do commit `284714d` na primeira utilização, verificado por SHA-256 e mantido fora do repositório deste site. O modelo e a lógica de decisão correm na ShardCloud; o agente envia as capturas e executa gestos de joystick no jogo. O teste regista o tempo de cada ciclo no Termux e apresenta mediana e P90 no site.

Esta política deteta inimigos, alterna a direção de patrulha quando não os vê e escolhe ataques com base no alcance. O jogo tem de estar no ecrã do LDPhone. A meta de 0,5 segundo por ciclo só pode ser validada com os tempos reais do LDPhone e da ShardCloud. O modelo original do PylaAI é distribuído sob CC BY-NC 4.0; o metadata ONNX também declara AGPL-3.0 para Ultralytics.

## Testes

Arranque, fila, consulta pelo agente, abertura simulada do convite, atualização de estado e inferência ONNX sobre uma imagem sintética foram testados localmente. A entrada real e o ciclo de jogo dependem do teste no LDPhone.


## Controlo do jogo

No LDPhone, instala OCR com `pkg install -y tesseract` e reinicia o agente usando o comando atualizado no painel. O botão de troféus tira um novo print; o agente tenta reconhecer o número da zona do perfil e envia-o ao painel. Esta leitura depende do layout mostrado no ecrã.

Para trocar de brawler, abre o print da conta e toca no ponto desejado. O agente converte o ponto à resolução do LDPhone, toca no jogo e tira outro print. Repete até selecionar o brawler.

O auto farm corre um ciclo contínuo: usa templates de estado do PylaAI fixados no commit `284714d` para identificar lobby, procura de partida e fim de jogo; inicia/avança os ecrãs correspondentes e aplica o modelo ONNX nas partidas. O botão Parar é verificado a cada poucos segundos. Os templates são descarregados e guardados na primeira utilização. A política de movimento/ataque é uma adaptação simplificada do projeto PylaAI; a validação final exige observar uma partida real no LDPhone.


No LDPhone com root, o agente usa os eventos multitouch do Android para manter o joystick pressionado entre imagens e disparar com um segundo dedo. Ao parar, sair do combate ou ocorrer um erro, solta ambos os toques. Se o dispositivo não expuser um ecrã multitouch acessível por root, o agente regista a falha no Termux e usa gestos longos como recurso alternativo.

## Menu flutuante no LDPhone

O projeto `android-overlay/` compila uma app Android externa. O APK para instalar está na release `overlay-v6`: https://github.com/0299jolgue/Usa-isto-gpt/releases/download/overlay-v6/brawl-room-menu.apk. O workflow **Build Android overlay** também guarda o APK no artefacto `brawl-room-menu-apk` da página **Actions** do GitHub. No LDPhone, instala o APK e abre **Brawl Room Menu**: `https://joinbrawl.shardweb.app` já vem preenchido. Concede a permissão **Mostrar sobre outras aplicações**, toca em **Ativar controlo por Acessibilidade** e ativa **Brawl Room Menu** nas definições. Depois carrega em **Abrir menu**. O menu ajusta o tamanho ao ecrã, pode ser arrastado e mostra as ações rápidas, a fila e o progresso do farm. O botão de atualização recarrega o menu e «Abrir painel» usa o navegador. Se o Android bloquear `input touchscreen`, o agente usa o serviço de Acessibilidade para mover e atacar. Se o Android recusar a instalação sobre o APK antigo por assinatura incompatível, desinstala o antigo e instala esta versão.

Dentro de **Comandos do Termux**, o menu tem instalação normal e reinstalação limpa com botões de copiar. A reinstalação limpa remove apenas os scripts antigos deste projeto no diretório Download do LDPhone e os ficheiros locais de identidade/tática do agente. Não apaga dados do Brawl Stars. Como gera uma nova identidade para o agente, o cartão anterior deve ser removido do painel depois de ligar o novo.

O WebView do APK tem uma sessão de login separada da do navegador. Ao abrir `/overlay` sem sessão, o servidor mostra o formulário diretamente e, depois de autenticar, apresenta o HUD sem redirecionamento HTTP. O APK 1.5 recarrega pedidos que recebam erro 5xx até três vezes e permite uma recarga manual sem cache pelo botão ⟳. Se o erro continuar, confirma `/health` e os logs da ShardCloud; um 502 de origem também afeta o WebView.

## Ranked

**Verificar Ranked** abre a seleção de modos no LDPhone, procura a opção por OCR e só marca a conta como disponível quando o jogo mostra Ranked selecionado com o botão Jogar. Uma opção bloqueada é reportada como bloqueada; um ecrã que não permita confirmação fica como desconhecido. **Jogar Ranked** repete a verificação antes de iniciar o ciclo de jogo. A disponibilidade fica guardada no painel por conta. A seleção e banimento de brawlers em drafts de patamares mais altos exigem intervenção no LDPhone; o agente espera até 120 segundos e pára com uma mensagem clara se o draft não for concluído. Ainda não houve validação de Ranked no LDPhone real.

O agente escolhe entre as táticas `aggressive`, `balanced` e `cautious` por amostragem de resultados. Depois de uma vitória ou derrota observada, guarda os totais no ficheiro privado `~/.brawl_room_tactics.json` do Termux e envia um resumo ao painel. Partidas sem resultado reconhecido não alteram a escolha. Isto adapta a seleção entre três políticas; não treina um novo modelo de visão nem garante melhoria em cada partida.

Durante a partida, a política estima a vida pela barra verde do jogador. Uma perda repentina de vida provoca uma esquiva curta enquanto continua a atacar se o inimigo está ao alcance; só suspende o ataque para regenerar quando o inimigo está longe. A curta distância mantém o auto fire pressionado entre imagens e usa o Super quando a área amarela do botão indica que está carregado. O movimento de patrulha muda de direção periodicamente, e o último alvo é lembrado por menos de um segundo se a deteção falhar num fotograma. No ecrã inicial o agente lê «Combate»/«Showdown» e, nesse modo, procura caixas pela cor, forma e barra de vida; aproxima-se antes de atacar, especialmente se reconhecer Shelly. O Termux regista `tática`, `vida`, número de inimigos e Super em cada ciclo. Estas heurísticas dependem da aparência atual do jogo e ainda precisam de validação em capturas reais do LDPhone.
