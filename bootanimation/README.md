# Boot animation — ultraminimal (Monochrome Night)

Pure **black + grey dots**. No brand hues.

**Sequence:** black → grey dotted **B** assembles → faint **BESTROM** → hold until boot ends.

```bash
python3 vendor/bestrom/bootanimation/generate.py
# → prebuilt/common/media/bootanimation.zip  (1080×2400, 30fps, store-only zip)
```

Wired in `config/common.mk` → `/product/media/bootanimation.zip`.
