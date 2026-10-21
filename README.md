# Brawl Stars: entrada em sala por código

Site Python para ShardCloud. A página solicita email do Supercell ID, PIN de seis dígitos e código da sala. O backend tenta obter a sessão de jogo e enviar `TeamJoinOrCreateRoomMessage` (14371) por TCP.

## Estado

O formulário e a sequência entre pedidos foram testados localmente com respostas simuladas. O login real **ainda não foi validado**. O endpoint antigo do Supercell ID pode não fornecer `bindToken`; se acontecer, o site indica esse bloqueio. A ligação TCP e a entrada na sala também precisam de teste com uma conta real. Não apresentes esta versão como pronta para uso.

## Execução

```bash
pip install -r requirements.txt
python server.py
```

Define `PORT` se necessário. O `Dockerfile` inicia a aplicação na porta configurada pela plataforma.

O processo guarda a sessão do PIN em memória durante até 10 minutos; uma reinicialização invalida tentativas pendentes. As credenciais não são gravadas em disco.
