import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Plus, Search } from 'lucide-react';
import './Select.css';

export type SelectOption = {
  value: string;
  label: string;
  description?: string;
  group?: string;
  keywords?: string;
  icon?: ReactNode;
  disabled?: boolean;
};

type SelectProps = {
  options: SelectOption[];
  value?: string;
  defaultValue?: string;
  onChange?: (value: string) => void;
  label: string;
  placeholder?: string;
  name?: string;
  disabled?: boolean;
  required?: boolean;
  searchable?: boolean;
  allowCustom?: boolean;
  className?: string;
  icon?: ReactNode;
  emptyText?: string;
  placement?: 'auto' | 'top' | 'bottom';
  compact?: boolean;
  displayValue?: string;
};

type MenuOption = SelectOption & { custom?: boolean };
type PopupPosition = { left: number; top: number; width: number; maxHeight: number; side: 'top' | 'bottom' };

export function Select({
  options, value, defaultValue, onChange, label, placeholder = '请选择…', name,
  disabled = false, required = false, searchable = false, allowCustom = false,
  className = '', icon, emptyText, placement = 'auto', compact = false, displayValue,
}: SelectProps) {
  const id = useId();
  const listboxId = `${id}-listbox`;
  const [internalValue, setInternalValue] = useState(defaultValue ?? '');
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeValue, setActiveValue] = useState<string | null>(null);
  const [position, setPosition] = useState<PopupPosition | null>(null);
  const [invalid, setInvalid] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const searchRowRef = useRef<HTMLDivElement>(null);
  const selectedValue = value ?? internalValue;
  const selectedOption = options.find(option => option.value === selectedValue);
  const canSearch = searchable || allowCustom;
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const customValue = query.trim();
  const isInvalid = required && !selectedValue && invalid;

  const optionGroups = useMemo(() => {
    const groups = new Map<string, SelectOption[]>();
    for (const option of options) {
      const key = option.group ?? '';
      const group = groups.get(key);
      if (group) group.push(option);
      else groups.set(key, [option]);
    }
    return Array.from(groups, ([group, items]) => ({ group, items }));
  }, [options]);

  const filteredGroups = useMemo(() => optionGroups.map(group => ({
    ...group,
    items: group.items.filter(option => !normalizedQuery || `${option.label} ${option.keywords ?? ''}`.toLocaleLowerCase().includes(normalizedQuery)),
  })).filter(group => group.items.length > 0), [optionGroups, normalizedQuery]);

  const customOption = useMemo<MenuOption | null>(() => {
    if (!allowCustom || !customValue || options.some(option => option.value.toLocaleLowerCase() === normalizedQuery || option.label.toLocaleLowerCase() === normalizedQuery)) return null;
    return { value: customValue, label: `使用“${customValue}”`, description: '确认并使用此自定义值', custom: true };
  }, [allowCustom, customValue, normalizedQuery, options]);

  const menuOptions = useMemo<MenuOption[]>(() => {
    const items: MenuOption[] = filteredGroups.flatMap(group => group.items);
    return customOption ? [...items, customOption] : items;
  }, [filteredGroups, customOption]);
  const activeIndex = menuOptions.findIndex(option => option.value === activeValue && !option.disabled);
  const activeId = open && activeIndex >= 0 ? `${id}-option-${activeIndex}` : undefined;
  const positioned = position !== null;

  const close = useCallback((restoreFocus = false) => {
    setOpen(false);
    setQuery('');
    setPosition(null);
    if (restoreFocus) triggerRef.current?.focus({ preventScroll: true });
  }, []);

  const openMenu = (edge: 'selected' | 'first' | 'last' = 'selected') => {
    if (disabled || triggerRef.current?.matches(':disabled')) return;
    const available = optionGroups.flatMap(group => group.items).filter(option => !option.disabled);
    const next = edge === 'last' ? available.at(-1) : edge === 'first' ? available[0] : available.find(option => option.value === selectedValue) ?? available[0];
    setQuery('');
    setActiveValue(next?.value ?? null);
    setOpen(true);
  };

  const choose = (option: MenuOption) => {
    if (option.disabled || disabled) return;
    if (value === undefined) setInternalValue(option.value);
    setInvalid(false);
    close(true);
    if (option.value !== selectedValue) onChange?.(option.value);
  };

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    const popup = popupRef.current;
    const list = listRef.current;
    if (!trigger || !popup || !list) return;
    const viewport = window.visualViewport;
    const viewportLeft = viewport?.offsetLeft ?? 0;
    const viewportTop = viewport?.offsetTop ?? 0;
    const viewportWidth = viewport?.width ?? window.innerWidth;
    const viewportHeight = viewport?.height ?? window.innerHeight;
    const inset = 12;
    const gap = 8;
    const bounds = trigger.getBoundingClientRect();
    const width = Math.min(Math.max(bounds.width, compact ? 240 : 260), Math.max(1, viewportWidth - inset * 2));
    popup.style.width = `${width}px`;
    const contentHeight = list.scrollHeight + (searchRowRef.current?.getBoundingClientRect().height ?? 0) + 2;
    const desiredHeight = Math.min(360, contentHeight);
    const availableHeight = Math.max(0, viewportHeight - inset * 2);
    const below = Math.min(availableHeight, Math.max(0, viewportTop + viewportHeight - inset - bounds.bottom - gap));
    const above = Math.min(availableHeight, Math.max(0, bounds.top - gap - viewportTop - inset));
    let side: 'top' | 'bottom' = placement === 'top' ? 'top' : 'bottom';
    const preferredSpace = side === 'top' ? above : below;
    const otherSpace = side === 'top' ? below : above;
    if (preferredSpace < desiredHeight && otherSpace > preferredSpace) side = side === 'top' ? 'bottom' : 'top';
    const maxHeight = Math.min(360, side === 'top' ? above : below);
    const height = Math.min(contentHeight, maxHeight);
    const left = Math.max(viewportLeft + inset, Math.min(bounds.left, viewportLeft + viewportWidth - inset - width));
    const anchoredTop = side === 'top' ? bounds.top - gap - height : bounds.bottom + gap;
    const top = Math.max(viewportTop + inset, Math.min(anchoredTop, viewportTop + viewportHeight - inset - height));
    setPosition(previous => previous && previous.left === left && previous.top === top && previous.width === width && previous.maxHeight === maxHeight && previous.side === side ? previous : { left, top, width, maxHeight, side });
  }, [compact, placement]);

  useLayoutEffect(() => {
    if (!open) return;
    updatePosition();
    let frame = 0;
    const schedulePosition = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(updatePosition);
    };
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(schedulePosition);
    if (triggerRef.current) observer?.observe(triggerRef.current);
    if (popupRef.current) observer?.observe(popupRef.current);
    window.addEventListener('resize', schedulePosition);
    window.addEventListener('scroll', schedulePosition, true);
    window.visualViewport?.addEventListener('resize', schedulePosition);
    window.visualViewport?.addEventListener('scroll', schedulePosition);
    return () => {
      window.cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener('resize', schedulePosition);
      window.removeEventListener('scroll', schedulePosition, true);
      window.visualViewport?.removeEventListener('resize', schedulePosition);
      window.visualViewport?.removeEventListener('scroll', schedulePosition);
    };
  }, [open, updatePosition, menuOptions]);

  useLayoutEffect(() => {
    if (open && positioned && canSearch) searchRef.current?.focus({ preventScroll: true });
  }, [open, positioned, canSearch]);

  useLayoutEffect(() => {
    if (!open || activeIndex >= 0) return;
    const available = menuOptions.filter(option => !option.disabled);
    setActiveValue((available.find(option => option.value === selectedValue) ?? available[0])?.value ?? null);
  }, [open, activeIndex, menuOptions, selectedValue]);

  useLayoutEffect(() => {
    if (!open || !activeId || !listRef.current) return;
    const item = document.getElementById(activeId);
    if (!item) return;
    const list = listRef.current;
    const listBounds = list.getBoundingClientRect();
    const itemBounds = item.getBoundingClientRect();
    if (itemBounds.top < listBounds.top + 4) list.scrollTop -= listBounds.top + 4 - itemBounds.top;
    else if (itemBounds.bottom > listBounds.bottom - 4) list.scrollTop += itemBounds.bottom - listBounds.bottom + 4;
  }, [open, activeId, normalizedQuery, position]);

  useEffect(() => {
    if (!open) return;
    const dismissOutside = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && !triggerRef.current?.contains(target) && !popupRef.current?.contains(target)) close();
    };
    document.addEventListener('pointerdown', dismissOutside, true);
    document.addEventListener('focusin', dismissOutside, true);
    return () => {
      document.removeEventListener('pointerdown', dismissOutside, true);
      document.removeEventListener('focusin', dismissOutside, true);
    };
  }, [open, close]);

  useEffect(() => {
    if (disabled) close();
  }, [disabled, close]);

  useEffect(() => {
    const form = triggerRef.current?.form;
    if (!form) return;
    const reset = () => {
      if (value === undefined) setInternalValue(defaultValue ?? '');
      setInvalid(false);
      close();
    };
    form.addEventListener('reset', reset);
    return () => form.removeEventListener('reset', reset);
  }, [value, defaultValue, close]);

  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.nativeEvent.isComposing || disabled) return;
    if (event.key === 'Tab') {
      if (open) {
        // The portalled search field must leave from the trigger's place in the tab order.
        if (event.target === searchRef.current) triggerRef.current?.focus({ preventScroll: true });
        close();
      }
      return;
    }
    if (event.key === 'Escape') {
      if (open) {
        event.preventDefault();
        event.stopPropagation();
        close(true);
      }
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    if (!open) {
      openMenu(event.key === 'End' || event.key === 'ArrowUp' ? 'last' : event.key === 'Home' ? 'first' : 'selected');
      return;
    }
    if (event.key === 'Enter') {
      if (activeIndex >= 0) choose(menuOptions[activeIndex]);
      return;
    }
    const available = menuOptions.map((option, index) => ({ option, index })).filter(item => !item.option.disabled);
    if (!available.length) return;
    const current = available.findIndex(item => item.index === activeIndex);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? available.length - 1 : event.key === 'ArrowDown' ? (current + 1) % available.length : (current < 0 ? available.length - 1 : (current - 1 + available.length) % available.length);
    setActiveValue(available[next].option.value);
  };

  const renderOption = (option: MenuOption, index: number) => {
    const optionId = `${id}-option-${index}`;
    const selected = selectedValue === option.value;
    return <div
      key={option.value}
      id={optionId}
      role="option"
      aria-label={option.label}
      aria-selected={selected}
      aria-disabled={option.disabled || undefined}
      aria-describedby={option.description ? `${optionId}-description` : undefined}
      className={`ea-select-option${option.custom ? ' ea-select-custom' : ''}`}
      data-active={index === activeIndex || undefined}
      data-selected={selected || undefined}
      onPointerMove={event => { if (event.pointerType !== 'touch' && !option.disabled) setActiveValue(option.value); }}
      onClick={event => { event.preventDefault(); choose(option); }}
    >
      {(option.icon || option.custom) && <span className="ea-select-option-icon" aria-hidden="true">{option.custom ? <Plus size={16} /> : option.icon}</span>}
      <span className="ea-select-option-copy"><span className="ea-select-option-label">{option.label}</span>{option.description && <span className="ea-select-description" id={`${optionId}-description`}>{option.description}</span>}</span>
      <span className="ea-select-check" aria-hidden="true">{selected && <Check size={15} strokeWidth={2.3} />}</span>
    </div>;
  };

  const popupStyle: CSSProperties = position ? { left: position.left, top: position.top, width: position.width, maxHeight: position.maxHeight } : { left: 0, top: 0, maxHeight: 360, visibility: 'hidden' };
  const triggerIcon = icon ?? selectedOption?.icon;
  let optionIndex = 0;

  return <div className={`ea-select${compact ? ' ea-select-compact' : ''} ${className}`}>
    <button
      ref={triggerRef}
      type="button"
      role="combobox"
      aria-label={label}
      aria-expanded={open}
      aria-haspopup="listbox"
      aria-controls={open ? listboxId : undefined}
      aria-activedescendant={activeId}
      aria-required={required || undefined}
      aria-invalid={isInvalid || undefined}
      disabled={disabled}
      className="ea-select-trigger"
      data-open={open || undefined}
      onClick={() => open ? close() : openMenu()}
      onKeyDown={handleKeyDown}
    >
      {triggerIcon && <span className="ea-select-trigger-icon" aria-hidden="true">{triggerIcon}</span>}
      <span className="ea-select-value" data-placeholder={displayValue === undefined && !selectedOption && !selectedValue || undefined}>{displayValue ?? selectedOption?.label ?? (selectedValue || placeholder)}</span>
      <ChevronDown size={14} className="ea-select-chevron" aria-hidden="true" />
    </button>
    {name !== undefined && <input type="hidden" name={name} value={selectedValue} disabled={disabled} />}
    {required && <input
      type="text"
      className="ea-select-validity"
      tabIndex={-1}
      aria-hidden="true"
      required
      disabled={disabled}
      value={selectedValue}
      onChange={() => {}}
      onFocus={() => triggerRef.current?.focus({ preventScroll: true })}
      onInvalid={event => { event.preventDefault(); setInvalid(true); triggerRef.current?.focus({ preventScroll: true }); openMenu(); }}
    />}
    {open && createPortal(<div
      ref={popupRef}
      className={`ea-select-popup${compact ? ' ea-select-popup-compact' : ''}`}
      style={popupStyle}
      data-placement={position?.side ?? 'bottom'}
      onKeyDown={handleKeyDown}
      onClick={event => event.stopPropagation()}
      onPointerDown={event => { event.stopPropagation(); if (event.button === 0 && event.pointerType !== 'touch' && event.target !== searchRef.current) event.preventDefault(); }}
    >
      {canSearch && <div className="ea-select-search" ref={searchRowRef}>
        <Search size={15} aria-hidden="true" />
        <input
          ref={searchRef}
          role="searchbox"
          aria-label={`搜索${label}`}
          aria-controls={listboxId}
          aria-activedescendant={activeId}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          placeholder={`搜索${label}…`}
          value={query}
          onChange={event => { setQuery(event.target.value); setActiveValue(null); }}
        />
      </div>}
      <div className="ea-select-options" ref={listRef} id={listboxId} role="listbox" aria-label={label}>
        {filteredGroups.map((group, groupIndex) => <div key={group.group} role={group.group ? 'group' : 'presentation'} aria-labelledby={group.group ? `${id}-group-${groupIndex}` : undefined} className="ea-select-group">
          {group.group && <div className="ea-select-group-label" id={`${id}-group-${groupIndex}`}>{group.group}</div>}
          {group.items.map(option => renderOption(option, optionIndex++))}
        </div>)}
        {customOption && renderOption(customOption, optionIndex)}
        {!menuOptions.length && <div className="ea-select-empty" role="presentation"><Search size={22} aria-hidden="true" /><span role="status">{emptyText ?? (normalizedQuery ? '没有找到匹配项' : '暂无可选项')}</span></div>}
      </div>
    </div>, document.body)}
  </div>;
}
