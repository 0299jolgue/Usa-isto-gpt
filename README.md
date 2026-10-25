# Entrar numa sala do Brawl Stars com o LDPhone

O site coloca códigos de sala numa fila. Um agente Python no Termux do LDPhone abre o convite oficial no Brawl Stars instalado. O próprio jogo trata do login da conta convidada e da ligação TCP ao servidor. O site mostra se o Android abriu o convite e se foi observado o pedido de entrada `14358` na rede; a presença na sala deve ser confirmada no jogo.

## Servidor

Importar este repositório para a ShardCloud. `main.py` inicia Flask com Waitress em `0.0.0.0` e na porta indicada por `PORT`, ou 80. O endereço inicial redireciona para `/bridge`.

## LDPhone

Com Brawl Stars oficial instalado e uma conta convidada já no menu, executar no Termux:

```sh
curl -fsSL https://brawl-stars-room-join.shardweb.app/agent.py -o /sdcard/Download/ldphone_agent.py
python /sdcard/Download/ldphone_agent.py https://brawl-stars-room-join.shardweb.app
```

O agente mostra um código de emparelhamento. Introduzi-lo em `/bridge` no navegador. O Termux tem de continuar a executar o agente. Depois de inserir o código da sala no site, o agente abre o convite oficial no LDPhone. Se `tcpdump` estiver instalado, tenta confirmar que o jogo enviou a mensagem `14358`.

## Estado dos testes

O serviço foi testado localmente com Waitress: arranque, `/health`, emparelhamento, fila, consulta pelo agente e atualização de estado. O comando Android foi verificado por simulação. Falta confirmar o convite no LDPhone e o serviço publicado na ShardCloud.

