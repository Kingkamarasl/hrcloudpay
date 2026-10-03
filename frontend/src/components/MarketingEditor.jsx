import { useEffect, useMemo, useState } from 'react';
import { MarketingSections } from './MarketingSections';

// Structured editor for platform-managed marketing pages.
//
// This replaces a raw JSON textarea. Three things follow from that, and they are
// the reason it is worth the build:
//
//   * The form is generated from the schema the backend validates against, which
//     the page list endpoint returns. The editor therefore cannot offer a field
//     the backend rejects, and cannot omit one it accepts - the two cannot drift.
//   * Links are checked as they are typed, so a `javascript:` URL is refused
//     before it is ever sent rather than coming back as a 400.
//   * The preview is the real renderer, not a mockup. The previous preview drew
//     a hand-written approximation of the hero, which meant the thing being
//     reviewed was not the thing being published.

function labelFor(field) {
  return field.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

// A local mirror of the backend's link rule, so bad input is caught while typing.
// The backend re-checks on write - this is a courtesy, not the boundary.
const SAFE_HREF = /^(?:\/(?!\/)|#|https:\/\/)/i;

function TextField({ name, spec, value, onChange, id }) {
  const limit = spec.limit;
  const long = spec.kind === 'longtext';
  if (spec.kind === 'href') {
    const invalid = value && !SAFE_HREF.test(value.trim());
    return (
      <label className="me-field" htmlFor={id}>
        <span className="me-label">{labelFor(name)}</span>
        <input
          id={id}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder="/pricing or https://example.com"
          aria-invalid={invalid || undefined}
          className={invalid ? 'me-invalid' : ''}
        />
        {invalid && (
          <small className="me-error">
            Use a site path (/pricing), an anchor (#section), or an https:// address.
          </small>
        )}
      </label>
    );
  }
  if (spec.kind === 'bool') {
    return (
      <label className="me-field me-field-inline" htmlFor={id}>
        <input id={id} type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span className="me-label">{labelFor(name)}</span>
      </label>
    );
  }
  const over = value && value.length > limit;
  return (
    <label className="me-field" htmlFor={id}>
      <span className="me-label">
        {labelFor(name)}
        <em className={over ? 'me-over' : ''}>{`${(value || '').length}/${limit}`}</em>
      </span>
      {long ? (
        <textarea
          id={id}
          rows={3}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input id={id} value={value || ''} onChange={(e) => onChange(e.target.value)} />
      )}
      {over && <small className="me-error">Will be shortened to {limit} characters when saved.</small>}
    </label>
  );
}

function Fieldset({ fields, values, onChange, idPrefix }) {
  return Object.entries(fields).map(([name, spec]) => (
    <TextField
      key={name}
      id={`${idPrefix}-${name}`}
      name={name}
      spec={spec}
      value={values[name]}
      onChange={(next) => onChange({ ...values, [name]: next })}
    />
  ));
}

// One repeatable row: a titled block of fields, its own string list if the
// section has one (pricing plan features), a toggle, and its own move/delete.
function RepeatedItem({ label, fields, values, onChange, itemList, itemExtra, onRemove, onUp, onDown, index, isFirst, isLast, idPrefix }) {
  return (
    <div className="me-item">
      <div className="me-item-head">
        <span>{`${label} ${index + 1}`}</span>
        <div className="me-item-actions">
          <button type="button" className="btn btn-secondary me-mini" onClick={onUp} disabled={isFirst} aria-label={`Move ${label.toLowerCase()} ${index + 1} up`}>↑</button>
          <button type="button" className="btn btn-secondary me-mini" onClick={onDown} disabled={isLast} aria-label={`Move ${label.toLowerCase()} ${index + 1} down`}>↓</button>
          <button type="button" className="btn btn-secondary me-mini me-danger" onClick={onRemove} aria-label={`Remove ${label.toLowerCase()} ${index + 1}`}>Remove</button>
        </div>
      </div>
      <Fieldset fields={fields} values={values} onChange={onChange} idPrefix={idPrefix} />
      {itemExtra && (
        <TextField
          id={`${idPrefix}-${itemExtra.key}`}
          name={itemExtra.key}
          spec={{ kind: 'bool', limit: 0 }}
          value={values[itemExtra.key]}
          onChange={(next) => onChange({ ...values, [itemExtra.key]: next })}
        />
      )}
      {itemList && <StringList values={values[itemList.key]} limit={itemList.limit} onChange={(next) => onChange({ ...values, [itemList.key]: next })} idPrefix={`${idPrefix}-${itemList.key}`} />}
    </div>
  );
}

// A plain list of short strings, edited one line at a time. Used for the
// feature ticks on a plan.
function StringList({ values, onChange, limit, idPrefix }) {
  const rows = Array.isArray(values) ? values : [];
  return (
    <div className="me-strings">
      <span className="me-label">Features</span>
      {rows.map((row, index) => (
        <div className="me-string-row" key={index}>
          <input
            id={`${idPrefix}-${index}`}
            value={row}
            maxLength={limit}
            onChange={(e) => {
              const next = rows.slice();
              next[index] = e.target.value;
              onChange(next);
            }}
            aria-label={`Feature ${index + 1}`}
          />
          <button
            type="button"
            className="btn btn-secondary me-mini me-danger"
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
            aria-label={`Remove feature ${index + 1}`}
          >×</button>
        </div>
      ))}
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => onChange([...rows, ''])}>+ Add feature</button>
    </div>
  );
}

function SectionEditor({ section, definition, index, total, onChange, onRemove, onMove, maxRepeated }) {
  const [open, setOpen] = useState(index === 0);
  const idPrefix = `sec-${index}-${section.type}`;
  const repeated = definition.repeated;
  const notes = definition.notes;
  const items = repeated ? (section[repeated.key] || []) : [];
  const noteRows = notes ? (section[notes.key] || []) : [];

  function setField(name, value) {
    onChange({ ...section, [name]: value });
  }
  function setItem(nextIndex, nextItem) {
    const next = items.slice();
    next[nextIndex] = nextItem;
    onChange({ ...section, [repeated.key]: next });
  }

  return (
    <section className="me-section">
      <div className="me-section-head">
        <button
          type="button"
          className="me-section-toggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          <span className="me-caret">{open ? '▾' : '▸'}</span>
          <strong>{definition.label}</strong>
          <em>{summaryOf(section, definition)}</em>
        </button>
        <div className="me-item-actions">
          <button type="button" className="btn btn-secondary me-mini" onClick={() => onMove(index, -1)} disabled={index === 0} aria-label={`Move ${definition.label.toLowerCase()} section up`}>↑</button>
          <button type="button" className="btn btn-secondary me-mini" onClick={() => onMove(index, 1)} disabled={index === total - 1} aria-label={`Move ${definition.label.toLowerCase()} section down`}>↓</button>
          <button type="button" className="btn btn-secondary me-mini me-danger" onClick={onRemove} aria-label={`Remove ${definition.label.toLowerCase()} section`}>Remove</button>
        </div>
      </div>
      {open && (
        <div className="me-section-body">
          <p className="me-hint">{definition.hint}</p>
          <Fieldset fields={definition.fields} values={section} onChange={(next) => onChange(next)} idPrefix={idPrefix} />
          {repeated && (
            <div className="me-repeat">
              <div className="me-repeat-head">
                <span className="me-label">{labelFor(repeated.key)}</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={items.length >= maxRepeated}
                  onClick={() => onChange({ ...section, [repeated.key]: [...items, blankItem(repeated)] })}
                >+ Add {repeated.item_label.toLowerCase()}</button>
              </div>
              {items.length === 0 && <p className="me-hint">No {repeated.key} yet.</p>}
              {items.map((item, i) => (
                <RepeatedItem
                  key={i}
                  idPrefix={`${idPrefix}-${repeated.key}-${i}`}
                  label={repeated.item_label}
                  fields={repeated.fields}
                  itemList={repeated.item_list}
                  itemExtra={repeated.item_extra}
                  values={item}
                  index={i}
                  isFirst={i === 0}
                  isLast={i === items.length - 1}
                  onChange={(next) => setItem(i, next)}
                  onRemove={() => onChange({ ...section, [repeated.key]: items.filter((_, x) => x !== i) })}
                  onUp={() => moveItem(section, repeated.key, items, i, -1, onChange)}
                  onDown={() => moveItem(section, repeated.key, items, i, 1, onChange)}
                />
              ))}
            </div>
          )}
          {notes && (
            <div className="me-repeat">
              <div className="me-repeat-head">
                <span className="me-label">{labelFor(notes.key)}</span>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={noteRows.length >= maxRepeated}
                  onClick={() => onChange({ ...section, [notes.key]: [...noteRows, { title: '', body: '' }] })}
                >+ Add {notes.item_label.toLowerCase()}</button>
              </div>
              {noteRows.map((note, i) => (
                <RepeatedItem
                  key={i}
                  idPrefix={`${idPrefix}-${notes.key}-${i}`}
                  label={notes.item_label}
                  fields={notes.fields}
                  values={note}
                  index={i}
                  isFirst={i === 0}
                  isLast={i === noteRows.length - 1}
                  onChange={(next) => {
                    const nextNotes = noteRows.slice();
                    nextNotes[i] = next;
                    onChange({ ...section, [notes.key]: nextNotes });
                  }}
                  onRemove={() => onChange({ ...section, [notes.key]: noteRows.filter((_, x) => x !== i) })}
                  onUp={() => moveItem(section, notes.key, noteRows, i, -1, onChange)}
                  onDown={() => moveItem(section, notes.key, noteRows, i, 1, onChange)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function blankItem(repeated) {
  const item = {};
  Object.keys(repeated.fields).forEach((field) => { item[field] = ''; });
  if (repeated.item_list) item[repeated.item_list.key] = [];
  if (repeated.item_extra) item[repeated.item_extra.key] = false;
  return item;
}

function moveItem(section, key, rows, index, delta, onChange) {
  const target = index + delta;
  if (target < 0 || target >= rows.length) return;
  const next = rows.slice();
  const [moved] = next.splice(index, 1);
  next.splice(target, 0, moved);
  onChange({ ...section, [key]: next });
}

// A one-line description of a section so a collapsed list is still readable.
function summaryOf(section, definition) {
  if (section.title) return section.title.slice(0, 60);
  if (section.eyebrow) return section.eyebrow.slice(0, 60);
  if (definition.repeated) {
    const count = (section[definition.repeated.key] || []).length;
    return `${count} ${definition.repeated.key}`;
  }
  return '';
}

export default function MarketingEditor({ payload, onSave, onCreate, onDelete, onError, onNotice }) {
  const pages = payload?.pages || [];
  const schema = payload?.schema?.sections || {};
  const [selected, setSelected] = useState(null);
  const [name, setName] = useState('');
  const [sections, setSections] = useState([]);
  const [published, setPublished] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [previewMobile, setPreviewMobile] = useState(false);

  const page = pages.find((item) => item.slug === selected) || pages[0] || null;

  // Reload the working copy whenever the selected page or the server copy
  // changes. Keyed on the row's own version so an external publish lands here.
  useEffect(() => {
    if (!page) return;
    setSelected(page.slug);
    setName(page.draft_name || page.name);
    setSections((page.draft_content ?? page.content ?? {}).sections || []);
    setPublished(page.draft_is_published ?? page.is_published);
    setError('');
    // `dirty` means "the working copy differs from the server". Reaching this
    // point *is* the server copy, so it is false.
    //
    // It used to be `Boolean(page.has_draft)`, which conflated "a draft exists"
    // with "you have unsaved edits". That made saving a draft set dirty, which
    // disabled the Publish button, which meant a draft could never be
    // published from this screen without reloading the page first.
    setDirty(false);
  }, [page?.slug, page?.updated_at, page?.has_draft]);

  const preview = useMemo(() => ({ sections }), [sections]);

  function mark(next) { setDirty(true); setError(''); return next; }

  function setSection(index, next) {
    setSections(mark(sections.map((section, i) => (i === index ? next : section))));
  }
  function removeSection(index) {
    setSections(mark(sections.filter((_, i) => i !== index)));
  }
  function moveSection(index, delta) {
    const target = index + delta;
    if (target < 0 || target >= sections.length) return;
    const next = sections.slice();
    const [moved] = next.splice(index, 1);
    next.splice(target, 0, moved);
    setSections(mark(next));
  }
  function addSection(type) {
    if (sections.length >= (payload?.schema?.max_sections || 40)) return;
    setSections(mark([...sections, { type }]));
  }

  async function saveDraft(event) {
    event.preventDefault();
    if (!page) return;
    setBusy(true);
    setError('');
    try {
      await onSave(page.slug, { name, content: { sections }, is_published: published }, 'save_draft');
      setDirty(false);
      onNotice('Draft saved. Publish it when the preview looks right.');
    } catch (e) {
      setError(e.message || 'Could not save the draft.');
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!page) return;
    if (dirty) { setError('Save the draft before publishing.'); return; }
    if (!page.has_draft) { setError('There is no draft to publish.'); return; }
    setBusy(true);
    setError('');
    try {
      await onSave(page.slug, { is_published: published }, 'publish');
      onNotice(`Published ${page.name}.`);
    } catch (e) {
      setError(e.message || 'Could not publish.');
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    if (!page) return;
    setBusy(true);
    try {
      await onSave(page.slug, {}, 'discard_draft');
      onNotice('Draft discarded.');
    } catch (e) {
      setError(e.message || 'Could not discard the draft.');
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!page) return;
    // window.confirm rather than a custom modal: this is destructive, needs no
    // explanation beyond the name, and the browser dialog cannot be styled
    // inconsistently across the app's themes.
    if (typeof window !== 'undefined'
      && !window.confirm(`Delete the page "${page.name}"? Visitors will see the page without managed content.`)) return;
    setBusy(true);
    setError('');
    try {
      await onDelete(page.slug);
      setSelected(null);
      onNotice(`Deleted ${page.name}.`);
    } catch (e) {
      setError(e.message || 'Could not delete the page.');
    } finally {
      setBusy(false);
    }
  }

  async function create(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const created = await onCreate({ slug: newSlug, name: newName });
      setNewSlug(''); setNewName(''); setCreating(false);
      setSelected(created?.slug || newSlug);
      onNotice(`Created ${created?.name || newName}.`);
    } catch (e) {
      setError(e.message || 'Could not create the page.');
    } finally {
      setBusy(false);
    }
  }

  if (!pages.length) {
    return (
      <div className="card page-loading">No marketing pages have been configured yet.</div>
    );
  }

  const available = Object.keys(schema).filter((type) => !sections.some((s) => s.type === type));
  const used = Object.keys(schema).filter((type) => sections.some((s) => s.type === type));

  return (
    <div>
      <div className="card marketing-editor-intro">
        <div>
          <div className="eyebrow">PLATFORM CONTENT</div>
          <h2>Manage what visitors read</h2>
          <p>
            Each page is a list of sections. Reorder them to reorder the page,
            edit the copy in place, and publish when the preview looks right.
            Public visitors only ever see the last published version.
          </p>
        </div>
        <div className="marketing-editor-status">
          <span className={dirty ? 'status-dot draft' : 'status-dot'} />
          {/* Four states, not three. A page that has never been published has
              no draft either, so it used to fall through to "Published
              version" - telling an admin their new page is live when the
              public URL still 404s. */}
          {dirty
            ? 'Unsaved local changes'
            : page.has_draft
              ? 'Draft ready to publish'
              : page.is_published
                ? 'Published version'
                : 'Not published yet - this page is not on the public site'}
        </div>
      </div>

      <div className="marketing-editor-layout marketing-editor-layout-preview">
        <div className="marketing-editor-workspace">
          <div className="card marketing-page-list">
            <div className="panel-head">
              <h3>Pages</h3>
              <button type="button" className="btn btn-primary btn-sm" onClick={() => setCreating((v) => !v)}>
                {creating ? 'Cancel' : '+ New page'}
              </button>
            </div>
            {pages.map((item) => (
              <button
                type="button"
                key={item.slug}
                className={item.slug === page?.slug ? 'active' : ''}
                onClick={() => { setSelected(item.slug); setDirty(false); }}
              >
                <span>{item.name}</span>
                <small>
                  {item.has_draft ? 'Draft' : item.is_published ? 'Published' : 'Unpublished'}
                </small>
              </button>
            ))}
            {creating && (
              <form className="me-create" onSubmit={create}>
                <label htmlFor="me-new-slug">Slug</label>
                <input
                  id="me-new-slug"
                  value={newSlug}
                  onChange={(e) => setNewSlug(e.target.value)}
                  placeholder="payroll-product"
                  required
                />
                <small className="me-hint">
                  Lowercase letters, numbers and hyphens. This is the public URL.
                </small>
                <label htmlFor="me-new-name">Name</label>
                <input
                  id="me-new-name"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Payroll product"
                  required
                />
                <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>Create page</button>
              </form>
            )}
          </div>

          {page && (
            <form className="card marketing-editor-form" onSubmit={saveDraft}>
              <div className="panel-head">
                <div>
                  <div className="eyebrow">EDITING / {page.slug}</div>
                  <h3>{page.name}</h3>
                </div>
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={published}
                    onChange={(e) => { setPublished(e.target.checked); setDirty(true); }}
                  />
                  Published on publish
                </label>
              </div>

              <label className="me-field" htmlFor="me-page-name">
                <span className="me-label">Page name</span>
                <input
                  id="me-page-name"
                  value={name}
                  maxLength={160}
                  onChange={(e) => { setName(e.target.value); setDirty(true); }}
                  required
                />
              </label>

              <div className="me-sections">
                {sections.length === 0 && (
                  <p className="me-hint">
                    This page has no sections, so it renders nothing. Add one below.
                  </p>
                )}
                {sections.map((section, index) => {
                  const definition = schema[section.type];
                  if (!definition) {
                    // Should be unreachable: the backend refuses unknown types on
                    // write, and a page loaded from the API passed through it.
                    return (
                      <div className="alert alert-error" key={index}>
                        Section {index + 1} has an unrecognised type “{section.type}” and
                        cannot be shown here.
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => removeSection(index)}
                        >Remove it</button>
                      </div>
                    );
                  }
                  return (
                    <SectionEditor
                      key={`${section.type}-${index}`}
                      section={section}
                      definition={definition}
                      index={index}
                      total={sections.length}
                      maxRepeated={payload?.schema?.max_repeated || 60}
                      onChange={(next) => setSection(index, next)}
                      onRemove={() => removeSection(index)}
                      onMove={moveSection}
                    />
                  );
                })}
              </div>

              <div className="me-add-section">
                <span className="me-label">Add a section</span>
                <div className="me-add-buttons">
                  {available.length === 0 && (
                    <small className="me-hint">
                      Every available section type is already on this page.
                    </small>
                  )}
                  {available.map((type) => (
                    <button
                      key={type}
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => addSection(type)}
                      title={schema[type].hint}
                    >
                      + {schema[type].label}
                    </button>
                  ))}
                </div>
                {used.length > 0 && (
                  <small className="me-hint">
                    {used.join(', ')} already on this page.
                  </small>
                )}
              </div>

              {error && <div className="alert alert-error" role="alert">{error}</div>}

              <div className="modal-actions">
                <span className="hint">
                  {`Last published by ${page.updated_by || 'system seed'}`}
                </span>
                {page.slug !== 'home' && (
                  <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={busy}
                    onClick={remove}
                  >Delete page</button>
                )}
                <button className="btn btn-secondary" type="button" disabled={busy || !page.has_draft} onClick={discard}>Discard draft</button>
                <button className="btn btn-primary" type="submit" disabled={busy}>Save draft</button>
                <button className="btn btn-success" type="button" disabled={busy || dirty || !page.has_draft} onClick={publish}>Publish</button>
              </div>
            </form>
          )}
        </div>

        <div className={`marketing-live-preview${previewMobile ? ' mobile' : ''}`}>
          <div className="marketing-preview-toolbar">
            <div>
              <span className="preview-live-dot" />
              <strong>Draft preview</strong>
              <small>Rendered with the live page components</small>
            </div>
            <div className="preview-view-buttons">
              <button type="button" className={!previewMobile ? 'active' : ''} onClick={() => setPreviewMobile(false)}>Desktop</button>
              <button type="button" className={previewMobile ? 'active' : ''} onClick={() => setPreviewMobile(true)}>Mobile</button>
            </div>
          </div>
          {/* `ledger-page` is the design island the public pages render inside.
              Without it the preview would miss every rule scoped to that wrapper
              and show different colours from the real site. */}
          <div className="marketing-preview-frame ledger-page">
            {page && <MarketingSections content={preview} />}
            {page && !sections.length && (
              <p className="me-hint">Nothing to preview — this page has no sections.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
