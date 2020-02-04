import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';
import ScheduleData from './ScheduleData.js';

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

function CheckboxGroup({ options, labels, selectedOptions, onChange, children }) {
  if (labels === undefined) {
    labels = options;
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

  return (
    <div className="form-group form-inline">
      { children }
      { checkboxes() }
    </div>
  );
}

function Event({ event, abbreviateTitles }) {
  return (
    <div className="schedule-event">
      <h3 title={ event.title } className={ abbreviateTitles ? 'abbreviate-titles' : null }>{ event.title }</h3>
      <p>{ event.startTime.toFormat('HH:mm') } to { event.endTime.toFormat('HH:mm') } | { event.venue }</p>
    </div>
  );
}

function Hour({ hour, content, abbreviateTitles }) {
  if (content.length === 0) { return null; }

  return (
    <div className="schedule-hour">
      <h2>{hour.toFormat('HH:mm')}</h2>
      <div className="schedule-events-container">
        { content.map(event => <Event key={event.id} event={event} abbreviateTitles={abbreviateTitles} />) }
      </div>
    </div>
  );
}

function Calendar({ schedule, abbreviateTitles }) {
  return schedule.hoursWithContent.map(hour => {
    return (
      <Hour key={hour.toISO()} hour={hour} content={schedule.contentForHour(hour)} abbreviateTitles={abbreviateTitles} />
    );
  });
}

function App() {
  const [year, setYear] = useState(2018);
  const [abbreviateTitles, setAbbreviateTitles] = useState(false);
  const [currentTime, setCurrentTime] = useState(DateTime.fromSQL('2018-08-31 09:00:00').setZone('Europe/London'));
  const [selectedVenues, setSelectedVenues] = useState([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState([]);

  const [rawSchedule, setRawSchedule] = useState(null);
  const [schedule, setSchedule] = useState(null);

  // Pull the correct year's schedule if the year changes.
  useEffect(() => {
    fetch(`/schedule/${year}.json`)
      .then(response => response.json())
      .then(body => {
        setRawSchedule(body)

        let newSchedule = new ScheduleData(body, { currentTime });
        setSchedule(newSchedule);

        setSelectedVenues(newSchedule.venues.map(v => v.name));
        setSelectedEventTypes([...newSchedule.eventTypes.map(t => t.id)]);
      });
  }, [year]);

  // Refilter the schedule if options change.
  useEffect(() => {
    if (rawSchedule == null) { return };

    console.log(selectedEventTypes);
    let newSchedule = new ScheduleData(rawSchedule, { currentTime, selectedVenues, selectedEventTypes });
    setSchedule(newSchedule);
  }, [currentTime, selectedVenues, selectedEventTypes]);

  if (schedule === null) {
    return <p>Loading...</p>;
  }

  function yearChanged(ev) {
    setYear(ev.target.value);
  }

  function currentTimeChanged(newValue) {
    setCurrentTime(newValue);
  }


  function selectOfficialVenues(ev) {
    ev.preventDefault();
    setSelectedVenues(schedule.venues.filter(v => v.official).map(v => v.name));
  }

  function selectAllVenues(ev) {
    ev.preventDefault();
    setSelectedVenues([...schedule.venues.map(v => v.name)]);
  }

  function selectNoVenues(ev) {
    ev.preventDefault();
    setSelectedVenues([]);
  }

  function selectAllEventTypes(ev) {
    ev.preventDefault();
    setSelectedEventTypes([...schedule.eventTypes.map(t => t.id)]);
  }

  function selectNoEventTypes(ev) {
    ev.preventDefault();
    setSelectedEventTypes([]);
  }

  return (
    <>
      <h1>Schedule</h1>
      <h3>Venues</h3>
      <CheckboxGroup
        options={ schedule.venues.map(v => v.name) }
        selectedOptions={ selectedVenues }
        onChange={ setSelectedVenues }>

        <p>
          <a href="#" onClick={ selectOfficialVenues }>Official Venues Only</a> | <a href="#" onClick={ selectAllVenues }>Select All</a> | <a href="#" onClick={ selectNoVenues }>Select None</a>
        </p>
      </CheckboxGroup>

      <h3>Event Types</h3>
      <CheckboxGroup
        options={ schedule.eventTypes.map(t => t.id) }
        selectedOptions={ selectedEventTypes }
        labels={ schedule.eventTypes.map(t => t.name) }
        onChange={ setSelectedEventTypes }>

        <p>
          <a href="#" onClick={ selectAllEventTypes }>Select All</a> | <a href="#" onClick={ selectNoEventTypes }>Select None</a>
        </p>
      </CheckboxGroup>

      <div className="form-group form-inline">
        <label htmlFor="scheduleYear">Year:</label>
        <select onChange={yearChanged} id="scheduleYear" value={year} className="form-control">
          <option>2012</option>
          <option>2014</option>
          <option>2016</option>
          <option>2018</option>
        </select>
      </div>

      <div className="form-group form-inline">
        <Checkbox checked={ abbreviateTitles } onChange={ setAbbreviateTitles }>Abbreviate titles</Checkbox>
      </div>
      <p>
        <label>Current time:</label>
        <DateTimePicker value={currentTime} onChange={currentTimeChanged} />
      </p>

      <Calendar schedule={ schedule } />
    </>
  )
}

export default App;
