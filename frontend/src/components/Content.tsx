import { Children, type ReactElement } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type {} from 'remark-parse';
import type { Processor } from 'unified';
import { CopyButton } from './ui';
import './Content.css';

function disableHtml(this: Processor) {
  const data = this.data();
  const extensions = data.micromarkExtensions || (data.micromarkExtensions = []);
  extensions.push({ disable: { null: ['htmlFlow', 'htmlText'] } });
}

function safeUrl(value: string) {
  const url = value.trim();
  if (!url || /[\u0000-\u0020\u007f\\]|%5c/i.test(url) || url.startsWith('//')) return undefined;
  const scheme = /^([^/?#]*):/.exec(url)?.[1].toLowerCase();
  if (scheme !== undefined && !['http', 'https', 'mailto'].includes(scheme)) return undefined;
  try {
    return ['http:', 'https:', 'mailto:'].includes(new URL(url, 'https://earthai.invalid').protocol) ? url : undefined;
  } catch {
    return undefined;
  }
}

const markdownComponents: Components = {
  a({ href, children, title }) {
    return href ? <a href={href} title={title} rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
  },
  img({ src, alt, title }) {
    const label = alt ? `图片：${alt}` : '查看图片';
    return typeof src === 'string' && src ? <a className="markdown-image-link" href={src} title={title} rel="noopener noreferrer">{label}</a> : <span className="markdown-image-link">{label}</span>;
  },
  table({ children }) {
    return <div className="markdown-table-scroll" role="region" aria-label="Markdown 表格" tabIndex={0}><table>{children}</table></div>;
  },
  pre({ children }) {
    const code = Children.only(children) as ReactElement<{ children?: string; className?: string }>;
    const value = (code.props.children || '').replace(/\n$/, '');
    const language = /(?:^|\s)language-(\S+)/.exec(code.props.className || '')?.[1] || 'text';
    return <div className="code-block"><div className="code-heading"><span>{language}</span><CopyButton value={value} /></div><pre>{children}</pre></div>;
  },
};

export function Content({ text }: { text: string }) {
  return <div className="rich-content markdown-content"><ReactMarkdown remarkPlugins={[remarkGfm, disableHtml]} components={markdownComponents} urlTransform={safeUrl}>{text}</ReactMarkdown></div>;
}
