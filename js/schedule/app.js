import React, { useState, useEffect } from 'react';
import loadSchedule from './loadSchedule.js';

function Event({ event }) {
  return (
    <div className="schedule-event">
      <h3>{ event.title }</h3>
    </div>
  );
}

function Hour({ hour, content }) {
  if (content.length === 0) { return null; }

  return (
    <div className="schedule-hour">
      <h2>{hour}</h2>
      { content.map(event => <Event key={event.id} event={event} />) }
    </div>
  );
}

function OptionsPanel({ onChange, options }) {
  console.log('Options', options);

  let [time, setTime] = useState(options.currentTime);

  function checkboxChanged(ev) {
    onChange(ev.target.name, ev.target.checked);
  }

  function changed(ev) {
    onChange(ev.target.name, ev.target.value);
  }

  function timeChanged(ev) {
    console.log(ev.target.value)
    setTime(ev.target.value);
  }

  return (
    <div className="options">
      <p>
        <label htmlFor="currentTime">Current time:</label>
        <input type="text" name="currentTime" value={time} onChange={timeChanged} onBlur={ () => onChange('currentTime', time) } />
      </p>
      <p>
        <label>
          <input type="checkbox" onChange={checkboxChanged} name="officialOnly" checked={options.officialOnly} />
          Only show main schedule events (no villages)
        </label>
      </p>
    </div>
  );
}

function App() {
  const [schedule, setSchedule] = useState(null);
  const [scheduleRequiresReload, setScheduleRequiresReload] = useState(true);
  const [contentOptions, setContentOptions] = useState({ currentTime: new Date().toISOString(), officialOnly: true });

  useEffect(() => {
    if (scheduleRequiresReload) {
      loadSchedule().then(result => {
        setScheduleRequiresReload(false);
        setSchedule(result);
      });
    }
  }, [schedule, setSchedule, scheduleRequiresReload, setScheduleRequiresReload]);

  // Push updated options down to the schedule.
  useEffect(() => {
    if (contentOptions !== null && schedule !== null) {
      schedule.setOptions(contentOptions);
    }
  }, [contentOptions]);

  if (schedule === null) {
    return <p>Loading...</p>;
  }

  function renderContent() {
    return schedule.hoursWithContent().map(hour => {
      return (
        <Hour key={hour} hour={hour} content={schedule.contentForHour(hour)} />
      );
    });
  }

  function changeOption(option, value) {
    let newOptions = Object.assign({}, contentOptions);
    newOptions[option] = value;

    setContentOptions(newOptions);
  }

  return (
    <div>
      <h1>Schedule</h1>
      <OptionsPanel onChange={changeOption} options={contentOptions} />

      { renderContent() }
    </div>
  );
}

export default App;
