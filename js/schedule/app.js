import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';
import ScheduleData from './ScheduleData.js';

function Event({ event }) {
  return (
    <div className="schedule-event">
      <h3>{ event.title }</h3>
      <p>{ event.startTime.toFormat('HH:mm') } to { event.endTime.toFormat('HH:mm') } | { event.venue }</p>
    </div>
  );
}

function Hour({ hour, content }) {
  if (content.length === 0) { return null; }

  return (
    <div className="schedule-hour">
      <h2>{hour.toFormat('HH:mm')}</h2>
      { content.map(event => <Event key={event.id} event={event} />) }
    </div>
  );
}

function Schedule({ year, mainEventsOnly, currentTime }) {
  const [rawSchedule, setRawSchedule] = useState(null);
  const [schedule, setSchedule] = useState(null);

  // Pull the correct year's schedule if the year changes.
  useEffect(() => {
    fetch(`/schedule/${year}.json`)
      .then(response => response.json())
      .then(body => setRawSchedule(body));
  }, [year]);

  // Refilter the schedule if options change.
  useEffect(() => {
    if (rawSchedule == null) { return };

    let newSchedule = new ScheduleData(rawSchedule, { mainEventsOnly, currentTime });
    setSchedule(newSchedule);
  }, [rawSchedule, mainEventsOnly, currentTime]);

  if (schedule === null) {
    return <p>Loading...</p>;
  }

  function renderContent() {
    return schedule.hoursWithContent.map(hour => {
      return (
        <Hour key={hour.toISO()} hour={hour} content={schedule.contentForHour(hour)} />
      );
    });
  }

  return (
    <div>
      { renderContent() }
    </div>
  );
}

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
        <label>Current time:</label>
        <DateTimePicker value={currentTime} onChange={currentTimeChanged} />
      </p>

      <Schedule year={ year } mainEventsOnly={ mainEventsOnly } currentTime={ currentTime } />
    </>
  )
}

export default App;
