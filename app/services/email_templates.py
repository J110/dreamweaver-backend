"""Magic-link email templates — three variants × two languages.

Per spec docs/specs/auth-magic-link-v1.md §9. Bilingual EN + Roman Hindi.
Mobile-responsive HTML; primary purple button matches app palette; footer
includes support@dreamvalley.app.

Public API:
  build_magic_link_email(magic_link_url, context, lang, username) ->
      (subject: str, html: str)

Contexts:
  signup_new       — warm welcome, new user
  login_existing   — minimal, returning user
  claim_existing   — reassuring migration framing
"""

from __future__ import annotations

from typing import Tuple

# Color palette mirrors src/app/pricing/page.module.css gradient buttons.
_PURPLE_GRADIENT = "linear-gradient(135deg, #7c5cff, #b58bff)"
_BG = "#0d0b2e"
_FG = "#ffffff"
_SUPPORT_EMAIL = "support@dreamvalley.app"


def _subject_for_context(context: str, lang: str) -> str:
    if context == "signup_new":
        return (
            "Dream Valley mein swagat hai — apna email verify karein"
            if lang == "hi"
            else "Welcome to Dream Valley — verify your email"
        )
    if context == "login_existing":
        return (
            "Aapka Dream Valley login link"
            if lang == "hi"
            else "Your Dream Valley login link"
        )
    if context == "claim_existing":
        return (
            "Aapka Dream Valley account secure ho raha hai"
            if lang == "hi"
            else "Securing your Dream Valley account"
        )
    # Fallback — should never happen
    return "Dream Valley"


def _button(href: str, label: str) -> str:
    return f"""
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center" style="margin:24px auto;">
      <tr>
        <td align="center" bgcolor="#7c5cff" style="border-radius:12px;">
          <a href="{href}"
             style="display:inline-block;padding:14px 26px;font-family:'Quicksand',Arial,sans-serif;
                    font-size:16px;font-weight:600;color:#ffffff;text-decoration:none;
                    border-radius:12px;
                    background-image:{_PURPLE_GRADIENT};
                    background-color:#7c5cff;">
            {label}
          </a>
        </td>
      </tr>
    </table>
    """


def _shell(title: str, intro_html: str, button_html: str, ignore_html: str) -> str:
    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:{_BG};font-family:'Quicksand',Arial,sans-serif;color:{_FG};">
  <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:{_BG};">
    <tr><td align="center" style="padding:32px 16px;">
      <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="max-width:520px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);border-radius:18px;">
        <tr><td style="padding:32px 28px;">
          <h1 style="margin:0 0 12px;font-size:22px;font-weight:700;color:{_FG};letter-spacing:-0.01em;">
            Dream Valley
          </h1>
          <div style="font-size:15px;line-height:1.55;color:rgba(255,255,255,0.92);">
            {intro_html}
          </div>
          {button_html}
          <div style="font-size:13px;line-height:1.5;color:rgba(255,255,255,0.6);margin-top:16px;">
            {ignore_html}
          </div>
        </td></tr>
      </table>
      <div style="font-size:12px;line-height:1.5;color:rgba(255,255,255,0.45);margin-top:16px;">
        Dream Valley · <a href="mailto:{_SUPPORT_EMAIL}" style="color:rgba(255,255,255,0.6);text-decoration:underline;">{_SUPPORT_EMAIL}</a>
      </div>
    </td></tr>
  </table>
</body></html>"""


# ── Templates ─────────────────────────────────────────────────


def _new_user_email(magic_link_url: str, lang: str) -> str:
    if lang == "hi":
        intro = (
            "<p>Swagat hai! Apna Dream Valley account banane ke liye neeche button "
            "dabaayein. Link 15 minute ke liye chalega aur sirf is email par.</p>"
        )
        button = _button(magic_link_url, "Email verify karein")
        ignore = (
            "Agar aapne sign up nahi kiya tha, to is email ko ignore kar dein."
        )
        title = "Dream Valley mein swagat hai"
    else:
        intro = (
            "<p>Welcome! Tap the button below to finish setting up your Dream Valley "
            "account. The link works for 15 minutes and only on this email.</p>"
        )
        button = _button(magic_link_url, "Verify email")
        ignore = (
            "If you didn't try to sign up, you can safely ignore this email."
        )
        title = "Welcome to Dream Valley"
    return _shell(title, intro, button, ignore)


def _login_email(magic_link_url: str, lang: str, username: str) -> str:
    name = username or ("dost" if lang == "hi" else "there")
    if lang == "hi":
        intro = (
            f"<p>Namaste <strong>{name}</strong> — log in karne ke liye neeche "
            "button dabaayein. Link 15 minute tak chalega.</p>"
        )
        button = _button(magic_link_url, "Log in karein")
        ignore = (
            "Agar aapne log in nahi maanga tha, to is email ko ignore kar dein."
        )
        title = "Dream Valley login"
    else:
        intro = (
            f"<p>Hi <strong>{name}</strong> — tap the button below to log in. "
            "The link works for 15 minutes.</p>"
        )
        button = _button(magic_link_url, "Log in")
        ignore = (
            "If you didn't request a login, you can safely ignore this email."
        )
        title = "Dream Valley login"
    return _shell(title, intro, button, ignore)


def _claim_email(magic_link_url: str, lang: str, username: str) -> str:
    name = username or ("dost" if lang == "hi" else "there")
    if lang == "hi":
        intro = (
            f"<p>Namaste <strong>{name}</strong> — Dream Valley mein security "
            "update aa raha hai. Apna account is email se claim karne ke liye "
            "neeche button dabaayein. <strong>Aapka username, kid profiles, "
            "aur kahaniyaan jaisi thi waisi hi rahengi.</strong> "
            "Link 15 minute tak chalega.</p>"
        )
        button = _button(magic_link_url, "Account claim karein")
        ignore = (
            "Agar aapko yeh email expect nahi tha, to "
            f"<a href=\"mailto:{_SUPPORT_EMAIL}\" "
            f"style=\"color:rgba(255,255,255,0.7);\">{_SUPPORT_EMAIL}</a> par "
            "contact karein — aapka account target ho sakta hai."
        )
        title = "Dream Valley account secure ho raha hai"
    else:
        intro = (
            f"<p>Hi <strong>{name}</strong> — we're upgrading Dream Valley's "
            "security. Tap the button below to claim your account with this "
            "email. <strong>Your username, kid profiles, and stories stay "
            "exactly the same.</strong> The link works for 15 minutes.</p>"
        )
        button = _button(magic_link_url, "Claim my account")
        ignore = (
            "If you didn't expect this email, please contact "
            f"<a href=\"mailto:{_SUPPORT_EMAIL}\" "
            f"style=\"color:rgba(255,255,255,0.7);\">{_SUPPORT_EMAIL}</a> "
            "— your account may have been targeted."
        )
        title = "Securing your Dream Valley account"
    return _shell(title, intro, button, ignore)


# ── Public API ────────────────────────────────────────────────


def build_magic_link_email(
    magic_link_url: str,
    context: str,
    lang: str,
    username: str = "",
) -> Tuple[str, str]:
    """Return (subject, html) for the requested context+lang.

    Falls back to login_existing for unknown contexts; this should never
    happen in practice (callers validate context upstream).
    """
    lang = "hi" if lang == "hi" else "en"
    subject = _subject_for_context(context, lang)
    if context == "signup_new":
        html = _new_user_email(magic_link_url, lang)
    elif context == "claim_existing":
        html = _claim_email(magic_link_url, lang, username)
    else:
        html = _login_email(magic_link_url, lang, username)
    return subject, html
