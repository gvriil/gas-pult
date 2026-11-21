"""Владелец 21.11: «из каждой задачи и каждого пункта брифинга — сразу вход в чат, чтобы продолжить работу; это очень
важно». Задача с живым чатом — открывает его; без чата — «Продолжить в чате» (новый чат, задача в поле ввода);
пункт брифинга и решение — «В чат» (пункт и источник в поле ввода). Ничего не отправляется само."""
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "src/gas_pult/web"


def test_core_helper():
    page = (WEB / "index.html").read_text(encoding="utf-8")
    assert ('const chatWith = (text, pid) => { newChat(pid); setTimeout(() => { $("input").value = text; grow();'
            in page)


def test_tasks_every_task_has_a_way_to_chat():
    js = (WEB / "js/tasks.js").read_text(encoding="utf-8")
    assert 'if (t.chat_now) a.push({ label: "Открыть чат «"' in js                # и в списке — «из чата «…»» (21.11)
    assert 'class="tsk-chat" data-chat=' in js
    assert 'if (!t.chat_now) a.push({ label: "Продолжить в чате"' in js and "chatWith([" in js


def test_brief_every_row_and_decision():
    js = (WEB / "js/brief.js").read_text(encoding="utf-8")
    assert '<button class="tochat" data-chat="${ROWS.push(r) - 1}"' in js
    assert '<button class="btn quiet sm" data-a="chat">В чат</button>' in js
    assert "chatWith(chatText(ROWS[+x.dataset.chat]))" in js
