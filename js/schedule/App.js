import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';
import Schedule from './Schedule.js';

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

function App() {
  const [year, setYear] = useState(2018);
  const [mainEventsOnly, setMainEventsOnly] = useState(false);
  const [abbreviateTitles, setAbbreviateTitles] = useState(false);
  const [currentTime, setCurrentTime] = useState(DateTime.fromSQL('2018-08-31 09:00:00').setZone('Europe/London'));

  function yearChanged(ev) {
    setYear(ev.target.value);
  }

  function mainEventsChanged(ev) {
    setMainEventsOnly(ev.target.checked);
  }

  function currentTimeChanged(newValue) {
    setCurrentTime(newValue);
  }

  return (
    <>
      <h1>Schedule</h1>
      <p>
        <label htmlFor="scheduleYear">Year:</label>
        <select onChange={yearChanged} id="scheduleYear" value={year}>
          <option>2012</option>
          <option>2014</option>
          <option>2016</option>
          <option>2018</option>
        </select>
      </p>
      <p>
        <label><input type="checkbox" checked={mainEventsOnly} onChange={mainEventsChanged} /> Main events only</label>
      </p>
      <p>
        <label><input type="checkbox" checked={abbreviateTitles} onChange={ ev => setAbbreviateTitles(ev.target.checked) } /> Abbreviate titles</label>
      </p>
      <p>
        <label>Current time:</label>
        <DateTimePicker value={currentTime} onChange={currentTimeChanged} />
      </p>

      <Schedule year={ year } mainEventsOnly={ mainEventsOnly } currentTime={ currentTime } abbreviateTitles={ abbreviateTitles } />
    </>
  )
}

export default App;
