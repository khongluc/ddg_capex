"""
Authentication (UltraID / Google via Streamlit OIDC) and authorization helpers
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any

import html as _html
import streamlit as st

import db

# Provider key in .streamlit/secrets.toml -> [auth.<key>]
PROVIDERS = {
    "ultraid": "🔐 Đăng nhập bằng UltraID",
    "google": "🟢 Đăng nhập bằng Google",
}


@dataclass
class CurrentUser:
    email: str
    name: str
    role: str
    sites: List[str] = field(default_factory=list)  # site codes
    depts: List = field(default_factory=list)       # (site code, phòng ban) cho vai trò Phòng ban

    @property
    def is_admin(self) -> bool:
        return self.role == db.ROLE_ADMIN

    @property
    def sees_all_sites(self) -> bool:
        return self.role in (db.ROLE_ADMIN, db.ROLE_VIEWER)

    @property
    def is_dept_user(self) -> bool:
        return self.role == db.ROLE_DEPT

    def allowed_depts(self, site_code: str) -> List[str]:
        return [d for s, d in self.depts if s == site_code]

    def visible_sites(self, all_site_codes: List[str]) -> List[str]:
        if self.sees_all_sites:
            return list(all_site_codes)
        if self.is_dept_user:
            return [s for s in all_site_codes if s in {sc for sc, _ in self.depts}]
        return [s for s in all_site_codes if s in self.sites]

    def can_edit_site(self, site_code: str, status: str) -> bool:
        if self.is_admin:
            return True
        if self.is_dept_user:
            return bool(self.allowed_depts(site_code)) and status in db.EDITABLE_STATUSES
        return self.role == db.ROLE_SITE_IT and site_code in self.sites and status in db.EDITABLE_STATUSES


def _icost_cfg() -> Dict[str, Any]:
    try:
        return dict(st.secrets.get("icost", {}))
    except Exception:
        return {}


def _configured_providers() -> List[str]:
    try:
        auth_cfg = st.secrets.get("auth", {})
    except Exception:
        return []
    return [p for p in PROVIDERS if p in auth_cfg]


def _is_logged_in() -> bool:
    try:
        return bool(st.user.is_logged_in)
    except Exception:
        return False


def logout():
    for key in ("dev_login_email", "login_logged", "metadata"):
        st.session_state.pop(key, None)
    if _is_logged_in():
        st.logout()
    else:
        st.rerun()


def _render_login_page(providers: List[str], dev_login: bool):
    # Màn hình trước đăng nhập: không hiển thị tên công ty / thông tin cấu hình nội bộ
    st.markdown("""
    <div style="max-width:420px;margin:72px auto 20px auto;text-align:center;">
        <h2 style="color:#0F2C59;margin-bottom:4px;">🔒 Đăng nhập</h2>
        <p style="color:#64748B;">Hệ thống nội bộ – chỉ dành cho người được cấp quyền.</p>
    </div>
    """, unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        for p in providers:
            st.button(PROVIDERS[p], key=f"login_{p}", use_container_width=True,
                      on_click=st.login, args=(p,))
        if not providers:
            if _is_local_request():
                st.warning("Chưa cấu hình nhà cung cấp đăng nhập. Xem `.streamlit/secrets.toml.example` (mục [auth.ultraid], [auth.google]).")
            else:
                st.info("Hệ thống đang được cấu hình, chưa thể đăng nhập. Vui lòng liên hệ quản trị.")
        if dev_login:
            with st.form("dev_login"):
                st.caption("⚠️ Chế độ đăng nhập thử (dev_login = true) - chỉ dùng khi phát triển")
                email = st.text_input("Email")
                if st.form_submit_button("Đăng nhập thử", use_container_width=True) and email.strip():
                    st.session_state["dev_login_email"] = email.strip().lower()
                    st.rerun()
    st.stop()


def _render_blocked(user: Dict[str, Any], message: str):
    st.markdown(f"""
    <div style="max-width:560px;margin:60px auto;padding:24px;border:1px solid #FDE68A;background:#FFFBEB;border-radius:12px;">
        <h4 style="margin-top:0;color:#92400E;">{message}</h4>
        <p style="color:#78350F;">Tài khoản: <b>{_html.escape(str(user.get('email')))}</b><br>
        Vui lòng liên hệ quản trị hệ thống để được phân quyền site lập ngân sách.</p>
    </div>
    """, unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        if st.button("Đăng xuất", use_container_width=True):
            logout()
    st.stop()


def _dev_login_allowed(providers: List[str]) -> bool:
    """Đăng nhập thử chỉ khi máy chủ Streamlit chỉ lắng nghe trên localhost (người ngoài không kết nối được)
    và chưa cấu hình nhà cung cấp đăng nhập / CSDL máy chủ. Không dựa vào header Host (client tự đặt được)."""
    try:
        from streamlit import config as _st_config
        address = str(_st_config.get_option("server.address") or "")
    except Exception:
        return False
    if address not in ("localhost", "127.0.0.1", "::1"):
        return False
    return not providers and not db.using_server_db()


def _is_local_request() -> bool:
    """Truy cập từ chính máy chạy app (localhost). Không có header (chạy test) cũng coi là local."""
    try:
        host = str(st.context.headers.get("Host") or "")
    except Exception:
        return True
    if not host:
        return True
    host = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    return host in ("localhost", "127.0.0.1", "[::1]")


def require_login() -> CurrentUser:
    """Show the login page until the visitor is authenticated and authorized; return the current user."""
    db.init_db()
    cfg = _icost_cfg()
    providers = _configured_providers()
    dev_login = bool(cfg.get("dev_login", False))
    if dev_login and not (_dev_login_allowed(providers) and _is_local_request()):
        # Đăng nhập thử chỉ dùng trên máy phát triển: trên server, ai cũng gõ được email admin
        dev_login = False
        st.session_state.pop("dev_login_email", None)
    admin_emails = {e.strip().lower() for e in cfg.get("admin_emails", [])}
    allowed_domains = [d.strip().lower().lstrip("@") for d in cfg.get("allowed_domains", [])]

    if _is_logged_in():
        info = st.user.to_dict()
        email = str(info.get("email") or "").strip().lower()
        name = str(info.get("name") or email)
        provider = str(info.get("provider") or info.get("iss") or "oidc")
        if not email:
            st.error("Nhà cung cấp đăng nhập không trả về email. Kiểm tra scope 'openid email profile'.")
            st.button("Đăng xuất", on_click=st.logout)
            st.stop()
        if info.get("email_verified") is False:
            _render_blocked({"email": email}, "Email chưa được xác minh bởi nhà cung cấp đăng nhập.")
    elif dev_login and st.session_state.get("dev_login_email"):
        email = st.session_state["dev_login_email"]
        name, provider = email.split("@")[0], "dev"
    else:
        _render_login_page(providers, dev_login)
        raise AssertionError("unreachable")

    if allowed_domains and email.split("@")[-1] not in allowed_domains:
        _render_blocked({"email": email}, "⛔ Email không thuộc tên miền được phép truy cập.")

    default_role = db.ROLE_ADMIN if email in admin_emails else db.ROLE_PENDING
    user = db.upsert_login(email, name, provider, default_role=default_role)
    if email in admin_emails and user["role"] != db.ROLE_ADMIN:
        db.save_user(email, user.get("name") or name, db.ROLE_ADMIN, user["sites"], actor="system:admin_emails")
        user = db.get_user(email)

    if "login_logged" not in st.session_state:
        db.log(email, "login", provider)
        st.session_state["login_logged"] = True

    if user["role"] == db.ROLE_PENDING:
        _render_blocked(user, "⏳ Tài khoản đang chờ quản trị phân quyền")
    if user["role"] == db.ROLE_DISABLED:
        _render_blocked(user, "⛔ Tài khoản đã bị khóa")
    if user["role"] == db.ROLE_DEPT and not user.get("depts"):
        _render_blocked(user, "⏳ Tài khoản chưa được phân phòng ban lập ngân sách")
    if user["role"] == db.ROLE_SITE_IT and not user["sites"]:
        _render_blocked(user, "⏳ Tài khoản chưa được phân site lập ngân sách")

    return CurrentUser(email=user["email"], name=user.get("name") or name, role=user["role"], sites=user["sites"],
                       depts=user.get("depts", []))
