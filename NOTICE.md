# Сторонние компоненты

gas-pult не включает в репозиторий чужой код или модели: всё ниже ставится менеджером пакетов
или скачивается командой `gas-pult voices install` на машине пользователя. У каждого компонента своя лицензия —
соблюдайте её наравне с лицензией gas-pult.

| Компонент | Зачем | Лицензия |
|---|---|---|
| [Piper](https://github.com/OHF-Voice/piper1-gpl) (`piper-tts`) | синтез речи | GPL-3.0 |
| [Голоса Piper](https://huggingface.co/rhasspy/piper-voices) (irina, dmitri, denis, ruslan) | модели голоса | см. карточку каждого голоса |
| [Silero Models](https://github.com/snakers4/silero-models) (`v5_ru`) | синтез речи | CC BY-NC-SA 4.0 — **только некоммерческое использование** |
| [PyTorch](https://pytorch.org) | исполнение Silero | BSD-3-Clause |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | распознавание голосовых | MIT |
| [Whisper](https://github.com/openai/whisper) (веса моделей) | распознавание голосовых | MIT |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) / FFmpeg | перекодирование аудио | BSD-2-Clause / LGPL-GPL |
| [NumPy](https://numpy.org), [SciPy](https://scipy.org) | вычисления | BSD-3-Clause |
| [T-one](https://huggingface.co/t-tech/T-one) (Т-Технологии, веса `model.onnx`) | потоковое распознавание речи, `gas-pult asr install` | Apache-2.0 |
| [ONNX Runtime](https://onnxruntime.ai) | исполнение T-one | MIT |

## Взято с переработкой

Слепой проверяющий (`src/gas_pult/templates/agents/`: агенты `slepaya-proverka*`, сторож
`slepaya_proverka_storozh.py`) — по мотивам `agents/slepoy.md` и `hooks/slepoy_guard.py` проекта
[claude-pipeline](https://github.com/SilantevBitcoin/claude-pipeline) (лицензия MIT, © 2026 автор claude-pipeline,
полный текст лицензии — в его репозитории). Текст и логика переписаны: сторож пускает только в пути из задания,
добавлен режим «как налоговая / как банк».

Разбиение на фразы по паузам и жадный декодер службы распознавания (`src/gas_pult/asr/tone.py`) — переложение
`tone/logprob_splitter.py` и `tone/decoder.py` из [voicekit-team/T-one](https://github.com/voicekit-team/T-one)
(лицензия Apache-2.0, © T-Technologies) без зависимостей kenlm, pyctcdecode и huggingface_hub; числа и порядок шагов
сохранены, понижение частоты 16 → 8 кГц добавлено.

Claude и Claude Code — товарные знаки Anthropic, PBC. Telegram — товарный знак Telegram FZ-LLC.
gas-pult не связан с этими компаниями.
