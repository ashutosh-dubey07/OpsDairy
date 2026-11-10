"""Browser-side password forms with live validation and submit-only transfer."""

import streamlit as st


_HTML = """
<div class="password-form">
  <div class="identity-field">
    <label for="account-username">Account username</label>
    <input id="account-username" type="text" autocomplete="username" spellcheck="false">
  </div>
  <div id="recovery-code-field" class="field" hidden>
    <label for="recovery-code">Recovery code</label>
    <div class="input-wrap">
      <input id="recovery-code" type="password" autocomplete="off" maxlength="1024">
      <button class="visibility-toggle" data-target="recovery-code" type="button" aria-label="Show recovery code">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>
      </button>
    </div>
  </div>
  <div class="field">
    <label id="password-label" for="account-password">Password</label>
    <div class="input-wrap">
      <input id="account-password" type="password" autocomplete="new-password" maxlength="1024" spellcheck="false">
      <button class="visibility-toggle" data-target="account-password" type="button" aria-label="Show password">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>
      </button>
    </div>
  </div>
  <section class="requirements" aria-label="Password requirements">
    <div class="requirements-title">Password requirements</div>
    <div class="requirement" data-rule="length"><span class="dot" aria-hidden="true"></span><span>At least 8 characters</span></div>
    <div class="requirement" data-rule="uppercase"><span class="dot" aria-hidden="true"></span><span>One uppercase letter</span></div>
    <div class="requirement" data-rule="lowercase"><span class="dot" aria-hidden="true"></span><span>One lowercase letter</span></div>
    <div class="requirement" data-rule="number"><span class="dot" aria-hidden="true"></span><span>One number</span></div>
    <div class="requirement" data-rule="symbol"><span class="dot" aria-hidden="true"></span><span>One symbol</span></div>
  </section>
  <div id="confirmation-field" class="field">
    <label id="confirmation-label" for="password-confirmation">Confirm password</label>
    <div class="input-wrap">
      <input id="password-confirmation" type="password" autocomplete="new-password" maxlength="1024" spellcheck="false">
      <button class="visibility-toggle" data-target="password-confirmation" type="button" aria-label="Show confirmation password">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>
      </button>
    </div>
    <p id="password-mismatch" class="mismatch" role="status" hidden>Passwords do not match.</p>
  </div>
  <button id="password-submit" class="submit-button" type="button" disabled>Create account</button>
</div>
"""

_CSS = """
.password-form {
  box-sizing: border-box;
  width: 100%;
  color: var(--st-text-color);
  font-family: var(--st-font);
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.password-form * { box-sizing: border-box; }
.field, .identity-field { display: flex; flex-direction: column; gap: 6px; }
.password-form label { font-size: 0.9rem; }
.input-wrap { position: relative; width: 100%; }
.password-form input {
  width: 100%;
  height: 42px;
  padding: 0 44px 0 12px;
  color: var(--st-text-color);
  background: var(--st-secondary-background-color);
  border: 1px solid var(--st-border-color);
  border-radius: 8px;
  font: inherit;
  outline: none;
}
.password-form input:focus { border-color: var(--st-primary-color); box-shadow: 0 0 0 1px var(--st-primary-color); }
.visibility-toggle {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  padding: 4px;
  color: var(--st-text-color);
  background: transparent;
  border: 0;
  border-radius: 5px;
  cursor: pointer;
}
.visibility-toggle:hover { background: var(--st-secondary-background-color); }
.visibility-toggle svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.8; }
.requirements {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--st-border-color);
  border-radius: 8px;
}
.requirements-title { margin-bottom: 2px; color: var(--st-secondary-text-color); font-size: 0.88rem; }
.requirement { display: flex; align-items: center; gap: 9px; color: #737373; font-size: 0.9rem; }
.requirement.satisfied { color: #16803c; }
.dot { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: #a0a0a0; }
.requirement.satisfied .dot { background: #16803c; }
.mismatch { margin: 0; color: #b42318; font-size: 0.82rem; }
.submit-button {
  align-self: flex-start;
  min-height: 40px;
  padding: 0 16px;
  color: white;
  background: var(--st-primary-color);
  border: 1px solid var(--st-primary-color);
  border-radius: 7px;
  font: inherit;
  cursor: pointer;
}
.submit-button:disabled { opacity: 0.5; cursor: not-allowed; }
[hidden] { display: none !important; }
"""

_JS = r"""
export default function(component) {
  const { data, parentElement, setTriggerValue } = component;
  const username = parentElement.querySelector("#account-username");
  const recoveryCode = parentElement.querySelector("#recovery-code");
  const recoveryField = parentElement.querySelector("#recovery-code-field");
  const password = parentElement.querySelector("#account-password");
  const confirmation = parentElement.querySelector("#password-confirmation");
  const confirmationField = parentElement.querySelector("#confirmation-field");
  const requirements = parentElement.querySelector(".requirements");
  const submit = parentElement.querySelector("#password-submit");
  const mismatch = parentElement.querySelector("#password-mismatch");
  const mode = ["login", "recover"].includes(data?.mode) ? data.mode : "register";

  recoveryField.hidden = mode !== "recover";
  confirmationField.hidden = mode === "login";
  requirements.hidden = mode === "login";
  password.autocomplete = mode === "login" ? "current-password" : "new-password";
  parentElement.querySelector("#password-label").textContent =
    mode === "recover" ? "New password" : "Password";
  parentElement.querySelector("#confirmation-label").textContent =
    mode === "recover" ? "Confirm new password" : "Confirm password";
  submit.textContent = mode === "recover" ? "Reset password" : mode === "login" ? "Sign in" : "Create account";

  const rules = {
    length: (value) => Array.from(value).length >= 8,
    uppercase: (value) => /\p{Lu}/u.test(value),
    lowercase: (value) => /\p{Ll}/u.test(value),
    number: (value) => /\p{Nd}/u.test(value),
    symbol: (value) => /[^\p{L}\p{N}\s]/u.test(value),
  };

  const update = () => {
    const value = password.value;
    let validPassword = value.length > 0;
    if (mode !== "login") {
      validPassword = true;
      for (const [name, check] of Object.entries(rules)) {
        const met = check(value);
        parentElement.querySelector(`[data-rule="${name}"]`).classList.toggle("satisfied", met);
        validPassword = validPassword && met;
      }
    }
    const matches = mode === "login" || (value.length > 0 && value === confirmation.value);
    mismatch.hidden = mode === "login" || confirmation.value.length === 0 || matches;
    submit.disabled = !(
      username.value.trim().length > 0 &&
      validPassword &&
      matches &&
      (mode !== "recover" || recoveryCode.value.trim().length > 0)
    );
  };

  const submitForm = () => {
    update();
    if (submit.disabled) return;
    const payload = { username: username.value.trim(), password: password.value };
    if (mode !== "login") payload.confirmation = confirmation.value;
    if (mode === "recover") payload.recovery_code = recoveryCode.value;
    password.value = "";
    confirmation.value = "";
    if (recoveryCode) recoveryCode.value = "";
    update();
    setTriggerValue("submitted", payload);
  };

  for (const input of [username, recoveryCode, password, confirmation]) {
    if (!input) continue;
    input.oninput = update;
    input.onkeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        submitForm();
      }
    };
  }

  for (const toggle of parentElement.querySelectorAll(".visibility-toggle")) {
    const input = parentElement.querySelector(`#${toggle.dataset.target}`);
    toggle.onclick = () => {
      const isVisible = input.type === "text";
      input.type = isVisible ? "password" : "text";
      toggle.setAttribute("aria-label", `${isVisible ? "Show" : "Hide"} ${toggle.dataset.target.replaceAll("-", " ")}`);
    };
  }

  submit.onclick = submitForm;

  update();
}
"""

_password_form = st.components.v2.component(
    name="opsdiary_password_form",
    html=_HTML,
    css=_CSS,
    js=_JS,
)


def render_password_form(mode: str, *, key: str):
    """Render an account form; send secret fields only on explicit submit."""
    if mode not in {"login", "register", "recover"}:
        raise ValueError("mode must be 'login', 'register', or 'recover'.")
    return _password_form(
        data={"mode": mode},
        key=key,
        width="stretch",
        height=230 if mode == "login" else 505 if mode == "register" else 610,
        on_submitted_change=lambda: None,
    )
