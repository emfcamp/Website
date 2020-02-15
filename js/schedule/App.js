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

  const [apiToken, setApiToken] = useState(null);

  // Get the user's API token
  useEffect(() => {
    let container = document.getElementById('schedule-app');
    let token = container.getAttribute('data-api-token');

    if (token !== 'None') { setApiToken(token); }
  }, []);

  // Pull the correct year's schedule if the year changes.
  useEffect(() => {
    fetch(`/schedule.json`)
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
  }, [currentTime, selectedVenues, selectedEventTypes, rawSchedule]);

  function toggleFavourite(event) {
    console.log("Setting favourite");
    console.log(event);

    let endpoint = event.source === 'database' ? `/api/proposal/${event.id}/favourite` : `/api/external/${Math.abs(event.id)}/favourite`;
    fetch(endpoint, { headers: { 'Authorization': apiToken, 'Content-Type': 'application/json' }, method: 'put', body: '{}' })
      .then((response) => response.json())
      .then((data) => {
        let schedule = JSON.parse(JSON.stringify(rawSchedule))
        let idx = schedule.findIndex(e => e.id === event.id);
        schedule[idx].is_fave = data.is_favourite;

        setRawSchedule(schedule);
      })
      .catch((error) => {
        console.log("Error toggling favourite:", event, error);
      });
  }


  if (schedule === null) {
    return <p>Loading...</p>;
  }

  let filterProps = {
    schedule, selectedVenues, setSelectedVenues, selectedEventTypes, setSelectedEventTypes, currentTime, setCurrentTime
  }

  return (
    <>
      <Filters {...filterProps} />
      <Calendar schedule={ schedule } toggleFavourite={ toggleFavourite } authenticated={ apiToken !== null } />
    </>
  );
}

export default App;
