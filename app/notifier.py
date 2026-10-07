import subprocess
import httpx
from app.config import settings

def send_windows_notification(title: str, message: str, link: str = ""):
    """Envoie une notification Windows native via winotify ou fallback PowerShell."""
    try:
        from winotify import Notification
        toast = Notification(
            app_id="VolAlerte",
            title=title,
            msg=message,
            duration="long"
        )
        if link:
            toast.add_actions(label="Voir l'offre", launch=link)
        toast.show()
        return True
    except Exception:
        # Fallback via PowerShell BurntToast ou balise système Windows
        try:
            ps_script = f"""
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName('text')
            $textNodes.Item(0).AppendChild($template.CreateTextNode('{title}')) > $null
            $textNodes.Item(1).AppendChild($template.CreateTextNode('{message}')) > $null
            $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('VolAlerte')
            $notification = [Windows.UI.Notifications.ToastNotification]::new($template)
            $notifier.Show($notification)
            """
            subprocess.run(["powershell", "-Command", ps_script], capture_output=True, timeout=5)
            return True
        except Exception:
            return False

async def send_telegram_notification(message: str) -> bool:
    """Envoie un message via l'API Telegram Bot."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception:
        return False

async def send_ntfy_notification(title: str, message: str, link: str = "") -> bool:
    """Envoie une notification sur ntfy.sh (service gratuit, push mobile et bureau)."""
    topic = settings.NTFY_TOPIC
    if not topic:
        return False

    url = f"https://ntfy.sh/{topic}"
    headers = {
        "Title": title.encode("utf-8"),
        "Priority": "high",
        "Tags": "airplane,rotating_light"
    }
    if link:
        headers["Click"] = link

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, content=message.encode("utf-8"), headers=headers)
            return resp.status_code == 200
    except Exception:
        return False

async def dispatch_alert(title: str, message: str, link: str = "", channels: list[str] = None) -> list[str]:
    """Diffuse l'alerte sur tous les canaux configurés."""
    active_channels = channels or settings.ALERT_CHANNELS
    sent_on = []

    if "windows" in active_channels:
        if send_windows_notification(title, message, link):
            sent_on.append("windows")

    if "telegram" in active_channels:
        if await send_telegram_notification(f"<b>{title}</b>\n\n{message}"):
            sent_on.append("telegram")

    if "ntfy" in active_channels:
        if await send_ntfy_notification(title, message, link):
            sent_on.append("ntfy")

    return sent_on
