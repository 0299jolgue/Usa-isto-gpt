# Brawl Stars: entrada em sala por código

Site Python para ShardCloud. A página aceita email do Supercell ID e PIN ou tenta criar uma conta convidada. Ambas as opções recebem o código da sala e tentam enviar `TeamJoinOrCreateRoomMessage` (14371) por TCP. Para alojamento Python na ShardCloud, `main.py` e `.shardcloud` são os ficheiros de arranque obrigatórios.

## Estado

Os formulários e a sequência entre pedidos foram testados localmente com respostas simuladas. O login real **ainda não foi validado**. A conta convidada reproduz o ID `0:0` e o token nulo do antigo cliente Java, mas o comportamento no servidor atual é desconhecido. O endpoint do Supercell ID pode não fornecer `bindToken`. A ligação TCP e a entrada na sala precisam de teste real.

## Execução

```bash
pip install -r requirements.txt
python main.py
```

Define `PORT` se necessário. O `Dockerfile` inicia a aplicação na porta configurada pela plataforma.

O processo guarda a sessão do PIN em memória durante até 10 minutos; uma reinicialização invalida tentativas pendentes. As credenciais não são gravadas em disco.
