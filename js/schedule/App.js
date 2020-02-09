import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';

import Calendar from './Calendar.js';
import Filters from './Filters.js';
import ScheduleData from './ScheduleData.js';

function App() {
  const [currentTime, setCurrentTime] = useState(DateTime.fromSQL('2018-08-31 09:00:00').setZone('Europe/London'));
  const [selectedVenues, setSelectedVenues] = useState([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState([])

  const [rawSchedule, setRawSchedule] = useState(null);
  const [schedule, setSchedule] = useState(null);

  // Pull the correct year's schedule if the year changes.
  useEffect(() => {
    fetch(`/schedule/2018.json`)
      .then(response => response.json())
      .then(body => {
        setRawSchedule(body);

        let newSchedule = new ScheduleData(body, { currentTime });
        setSchedule(newSchedule);

        setSelectedVenues(newSchedule.venues.map(v => v.name));
        setSelectedEventTypes([...newSchedule.eventTypes.map(t => t.id)]);
      });
  }, []);

  // Refilter the schedule if options change.
  useEffect(() => {
    if (rawSchedule == null) { return };

    let newSchedule = new ScheduleData(rawSchedule, { currentTime, selectedVenues, selectedEventTypes });
    setSchedule(newSchedule);
  }, [currentTime, selectedVenues, selectedEventTypes]);

  if (schedule === null) {
    return <p>Loading...</p>;
  }

  let filterProps = {
    schedule, selectedVenues, setSelectedVenues, selectedEventTypes, setSelectedEventTypes, currentTime, setCurrentTime
  }

  return (
    <>
      <Filters {...filterProps} />
      <Calendar schedule={ schedule } />
    </>
  );
}

export default App;
