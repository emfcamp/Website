import React, { useState, useEffect } from 'react';

function DateTimePicker({ value, onChange }) {
  let date = value.toISODate();
  let time = value.toFormat('HH:mm');

  function dateChanged(ev) {
    let newValue = DateTime.fromISO(`${ev.target.value}T${time}`)
    onChange(newValue);
  }

  function timeChanged(ev) {
    let newValue = DateTime.fromISO(`${date}T${ev.target.value}`)
    onChange(newValue);
  }

  return (
    <>
      <input type="date" value={date} onChange={dateChanged} />
      <input type="time" value={time} onChange={timeChanged} />
    </>
  );
}

function Checkbox({ checked, onChange, children }) {
  return (
    <label className="checkbox"><input type="checkbox" checked={checked} onChange={ ev => onChange(ev.target.checked) } /> { children }</label>
  );
}

function CheckboxGroup({ options, labels, selectedOptions, onChange, children, filters }) {
  if (labels === undefined) {
    labels = options;
  }

  if (filters === undefined) {
    filters = [];
  }

  function selectAll(ev) {
    ev.preventDefault();
    onChange([...options]);
  }

  function selectNone(ev) {
    ev.preventDefault();
    onChange([]);
  }

  function toggle(option, value) {
    if (value) {
      onChange([...options, option]);
    } else {
      onChange(selectedOptions.filter(o => o !== option));
    }
  }

  function checkboxes() {
    return options.map((option, index) => {
      return <Checkbox checked={ selectedOptions.indexOf(option) !== -1 } key={ option } onChange={ value => toggle(option, value) }>{ labels[index] }</Checkbox>;
    });
  }

  let defaultFilters = [
    { name: "Select All", callback: selectAll },
    { name: "Select None", callback: selectNone }
  ]
  filters = [...filters, ...defaultFilters];

  return (
    <div className="form-group form-inline">
      <p>
        { filters.map(f => <a href="#" onClick={ f.callback }>{ f.name }</a>) }
      </p>
      { checkboxes() }
    </div>
  );
}

export { DateTimePicker, Checkbox, CheckboxGroup };
