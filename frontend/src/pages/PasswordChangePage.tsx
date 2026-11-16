import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { api, errorMessage } from '../lib/api';
import { Brand } from '../components/Brand';
import { Button, Field } from '../components/ui';

export function PasswordChangePage() {
  const { retry, logout } = useAuth();
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  return <main className="password-change-page"><section className="password-change-card"><Brand /><h1>设置新的登录密码</h1><p>初始密码或管理员重置的密码需要先修改，之后才能使用平台。默认管理员初始账号为 admin，密码为 admin；更改后不会因重启而重置。</p><form onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); setError(''); if (data.get('new_password') !== data.get('confirm_password')) { setError('两次输入的新密码不一致'); return; } setBusy(true); void api.post('/auth/password', { current_password: data.get('current_password'), new_password: data.get('new_password') }).then(() => retry()).catch(err => setError(errorMessage(err))).finally(() => setBusy(false)); }}><Field label="当前密码" required><input name="current_password" type="password" required autoComplete="current-password" /></Field><Field label="新密码" required hint="至少8位，不能与当前密码相同"><input name="new_password" type="password" minLength={8} maxLength={256} required autoComplete="new-password" /></Field><Field label="确认新密码" required><input name="confirm_password" type="password" minLength={8} required autoComplete="new-password" /></Field>{error && <div className="inline-error" role="alert">{error}</div>}<div className="password-change-actions"><Button type="button" variant="ghost" onClick={() => { void logout(); }}>退出登录</Button><Button busy={busy} type="submit"><KeyRound size={16} />更新密码并继续</Button></div></form></section></main>;
}
