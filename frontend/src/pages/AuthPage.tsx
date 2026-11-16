import { useState } from 'react';
import { Activity, ArrowLeft, ArrowRight, Eye, EyeOff, Globe2, LockKeyhole, ShieldCheck } from 'lucide-react';
import { Button, Field } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { errorMessage } from '../lib/api';
import { Brand } from '../components/Brand';
import { useBranding } from '../context/BrandingContext';
import './AuthPage.css';

export function AuthPage() {
  const { login, error: connectionError, retry } = useAuth();
  const brand = useBranding();
  const [register, setRegister] = useState(false);
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  return <div className={`auth-page${connectionError || error ? ' auth-has-feedback' : ''}`}>
    <div className="auth-story">
      <a className="brand brand-auth" href="/"><Brand compact /></a>
      <div className="auth-story-content">
        <div className="eyebrow"><span className="live-dot" /> AI 驱动 · 人机协作</div>
        <h1>复杂运维，<br />从容以对<span>。</span></h1>
        <p>连接、洞察、执行。<br />让每一步运维，都清晰可控。</p>
        <div className="auth-benefits">
          <div><span className="auth-benefit-icon"><Globe2 size={18} /></span><div><strong>基础设施，轻松连接</strong><p>服务器与集群，一站协作</p></div></div>
          <div><span className="auth-benefit-icon"><ShieldCheck size={18} /></span><div><strong>重要操作，由你确认</strong><p>让智能执行，始终有边界</p></div></div>
          <div><span className="auth-benefit-icon"><Activity size={18} /></span><div><strong>执行过程，全程可追溯</strong><p>实时跟进，完整保留轨迹</p></div></div>
        </div>
      </div>
      <div className="auth-story-footer"><span>{brand.name} · {brand.tagline}</span><span>为可靠而生</span></div>
    </div>
    <main className="auth-form-panel">
      <a className="auth-mobile-brand" href="/"><Brand compact /></a>
      <div className="auth-form-wrap">
        <div className="auth-overline">开启更轻盈的运维方式</div>
        <h2>{register ? '创建你的工作空间' : '欢迎回来'}</h2>
        <p className="auth-intro">{register ? '连接基础设施，从这里开始。' : '登录你的智能运维工作空间。'}</p>
        {connectionError && <div className="inline-error" role="alert"><span>服务连接异常：{connectionError}</span><button type="button" className="text-button" onClick={() => { void retry(); }}>重试</button></div>}
        <form onSubmit={event => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          setError('');
          setBusy(true);
          void login(String(form.get('email')), String(form.get('password')), register ? String(form.get('name')) : undefined)
            .catch(err => setError(errorMessage(err)))
            .finally(() => setBusy(false));
        }}>
          {register && <Field label="怎么称呼你" required><input name="name" autoComplete="name" placeholder="你的姓名或团队昵称" maxLength={60} required /></Field>}
          <Field label={register ? '电子邮箱' : '账号或电子邮箱'} required><input name="email" type={register ? 'email' : 'text'} autoComplete="username" placeholder={register ? 'you@company.com' : 'admin 或你的电子邮箱'} required /></Field>
          <Field label="密码" required hint={register ? '至少 8 位，建议包含字母和数字' : undefined}>
            <div className="password-input"><input name="password" aria-label="密码" type={visible ? 'text' : 'password'} autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 8 : undefined} placeholder={register ? '设置安全密码' : '输入你的密码'} required /><button type="button" aria-label={visible ? '隐藏密码' : '显示密码'} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
          </Field>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <Button type="submit" className="auth-submit" busy={busy}>{register ? '创建账户' : '登录工作空间'}<ArrowRight size={18} /></Button>
        </form>
        <div className="auth-toggle">{register ? '已经有账户？' : `第一次使用 ${brand.name}？`}<button type="button" onClick={() => { setRegister(!register); setError(''); }}>{register ? '返回登录' : '免费创建账户'}{register ? <ArrowLeft size={14} /> : <ArrowRight size={14} />}</button></div>
        <div className="auth-security"><LockKeyhole size={14} /><span>独立空间 · 凭据加密存储 · 会话安全认证</span></div>
      </div>
      <footer className="auth-form-footer">把时间留给创造，把重复交给智能。</footer>
    </main>
  </div>;
}
