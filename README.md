# Autodespliegue MT · skills para tu agente

Esto le enseña a tu agente (Claude Code u otro) a preparar tu repositorio para
**despliega.multitecua.com**: Dockerfile, `$PORT`, Firestore, secretos, y una comprobación
que tiene que salir bien antes de hacer push.

## Instalar en Claude Code

```
/plugin marketplace add Multitec-UA/autodespliegue-skills
/plugin install autodespliegue-mt@multitec-ua
```

Después, dile a tu agente: *"prepara este repositorio para el autodespliegue de Multitec"*.

## Sin Claude Code

Descarga `autodespliegue-mt.zip` desde la Guía del panel y copia la carpeta
`skills/autodespliegue-mt` donde tu agente lea instrucciones (por ejemplo `.claude/skills/`,
o pega `SKILL.md` en sus instrucciones). La comprobación funciona sola, solo con Python 3:

```
python3 skills/autodespliegue-mt/scripts/check_service.py --build .
```

Sale con 0 si está listo, 1 si hay avisos, 2 si fallaría en la plataforma, 3 si no pudo
comprobarlo (por ejemplo, sin Docker).

---

**English.** A Claude Code plugin that teaches your agent the Autodespliegue MT contract.
Install with the two `/plugin` commands above, or copy `skills/autodespliegue-mt` by hand.
Self-test: `bash plugins/autodespliegue-mt/skills/autodespliegue-mt/tests/run.sh --build`.
