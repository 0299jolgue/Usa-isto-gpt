# Entrar numa sala do Brawl Stars com o LDPhone

O site envia códigos de sala para um agente Python no Termux do LDPhone. O agente abre o convite oficial no Brawl Stars instalado. O próprio jogo trata do login da conta convidada e da ligação TCP ao servidor.

## Servidor

Importa este repositório para a ShardCloud. `main.py` inicia Flask com Waitress em `0.0.0.0` na porta indicada por `PORT`, ou 80. A página inicial redireciona para `/bridge`.

## Instalação no LDPhone

Na página `/bridge` aparece **um único comando** para o Termux. Executa-o uma vez e deixa o agente aberto. A partir daí, escreve apenas o código ou link da sala no site. O agente abre o convite automaticamente.

O site distingue entre convite aberto e pedido de entrada `14358` observado na rede. A presença na sala deve ser confirmada no ecrã do jogo.

## Teste da IA

O botão **Testar IA durante 20 segundos** abre o jogo, tenta iniciar uma partida e depois processa capturas do LDPhone no servidor. O modelo ONNX de deteção de jogadores do [PylaAI](https://github.com/PylaAI/PylaAI) é descarregado do commit `284714d` na primeira utilização, verificado por SHA-256 e mantido fora do repositório deste site. O modelo e a lógica de decisão correm na ShardCloud; o agente envia as capturas e executa gestos de joystick no jogo. O teste regista o tempo de cada ciclo no Termux e apresenta mediana e P90 no site.

Esta é uma primeira política de ataque ao inimigo mais próximo e movimento até ao centro quando não encontra inimigos. O jogo tem de estar no ecrã do LDPhone. A meta de 0,5 segundo por ciclo só pode ser validada com os tempos reais do LDPhone e da ShardCloud. O modelo original do PylaAI é distribuído sob CC BY-NC 4.0; o metadata ONNX também declara AGPL-3.0 para Ultralytics.

## Testes

Arranque, fila, consulta pelo agente, abertura simulada do convite, atualização de estado e inferência ONNX sobre uma imagem sintética foram testados localmente. A entrada real e o ciclo de jogo dependem do teste no LDPhone.
