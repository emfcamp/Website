import React from 'react';

function OptionsPanel({ onChange, options }) {
  console.log('Options', options);

  function checkboxChanged(ev) {
    onChange(ev.target.name, ev.target.checked);
  }

  function changed(ev) {
    onChange(ev.target.name, ev.target.value);
  }

  function timeChanged(ev) {
    setTime(ev.target.value);
  }

  return (
    <div className="options">
      {/* <p> */}
      {/*   <label htmlFor="currentTime">Current time:</label> */}
      {/*   <input type="text" name="currentTime" value={options.currentTime} onChange={timeChanged} onBlur={ () => onChange('currentTime', time) } /> */}
      {/* </p> */}
      <p>
        <label>
          <input type="checkbox" onChange={checkboxChanged} name="officialOnly" checked={options.officialOnly} />
          Only show main schedule events (no villages)
        </label>
      </p>
    </div>
  );
}

export default OptionsPanel;
