# Entrar na sala de Brawl Stars

Site Python para ShardCloud. Abre `/`, introduz o código da sala, os dois números do ID da conta e o token. O resultado aparece na página; não é preciso terminal.

## ShardCloud

Importa este repositório do GitHub e seleciona a construção por `Dockerfile`. A aplicação escuta na porta indicada por `PORT` (8000 por defeito). A raiz `/` é o site. O Dockerfile copia apenas `client.py` e `server.py`, excluindo os dumps binários do servidor.

O token só fica na memória durante a tentativa. Usa o site através de HTTPS e não publiques o token no GitHub.

## Linha de comando opcional

```sh
python -m pip install -r requirements.txt
python client.py CODIGO_DA_SALA
```

Para entrar numa conta existente, passa os dados localmente:

```sh
BS_HI=0 BS_LO=123456789 BS_TOKEN='token-da-conta' python client.py CODIGO_DA_SALA
```

O cliente tenta obter a versão e a fingerprint atualizadas através da resposta de erro `7` do servidor. A chave pública foi extraída do dump em memória; o ID de entrada por código é `14371`. O formato da mensagem foi inferido por desmontagem ARM64. A ligação real aos servidores oficiais e a entrada na sala ainda precisam de ser verificadas, pois este ambiente não consegue resolver `game.brawlstarsgame.com` e não tem credenciais da conta.

Não coloques o token em repositórios ou mensagens públicas.
