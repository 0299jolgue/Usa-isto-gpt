# Entrar numa sala do Brawl Stars com o LDPhone

O site envia códigos de sala para um agente Python no Termux do LDPhone. O agente abre o convite oficial no Brawl Stars instalado. O próprio jogo trata do login da conta convidada e da ligação TCP ao servidor.

## Servidor

Importa este repositório para a ShardCloud. `main.py` inicia Flask com Waitress em `0.0.0.0` na porta indicada por `PORT`, ou 80. A página inicial redireciona para `/bridge`.

## Instalação no LDPhone

Na página `/bridge` aparece **um único comando** para o Termux. Executa-o uma vez e deixa o agente aberto. A partir daí, escreve apenas o código ou link da sala no site. O agente abre o convite automaticamente.

O site distingue entre convite aberto e pedido de entrada `14358` observado na rede. A presença na sala deve ser confirmada no ecrã do jogo.

## Testes

Arranque, fila, consulta pelo agente, abertura simulada do convite e atualização de estado foram testados localmente. A entrada real no jogo depende do teste no LDPhone.
