import React, { useState, useEffect } from 'react';
import { DateTime } from 'luxon';

import Calendar from './Calendar.js';
import Filters from './Filters.js';
import ScheduleData from './ScheduleData.js';
import Messages from './Messages.js';

function now() {
  return DateTime.fromMillis(Date.now(), { zone: 'Europe/London' });
}

function App() {
  const [currentTime, setCurrentTime] = useState(now());
  const [selectedVenues, setSelectedVenues] = useState([]);
  const [selectedEventTypes, setSelectedEventTypes] = useState([]);
  const [selectedAgeRanges, setSelectedAgeRanges] = useState([]);
  const [onlyFavourites, setOnlyFavourites] = useState(false);
  const [debug, setDebug] = useState(false);

  const [rawSchedule, setRawSchedule] = useState(null);
  const [schedule, setSchedule] = useState(null);

  const [apiToken, setApiToken] = useState(null);

  // Get the user's API token
  useEffect(() => {
    let container = document.getElementById('schedule-app');
    let token = container.getAttribute('data-api-token');
    let debug = container.getAttribute('data-debug');

    if (token !== 'None') { setApiToken(token); }
    if (debug === 'True') { setDebug(true); }
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
        setSelectedAgeRanges([...newSchedule.ageRanges]);
      });
  }, []);

  // Refilter the schedule if options change.
  useEffect(() => {
    if (rawSchedule == null) { return };

    let newSchedule = new ScheduleData(rawSchedule, { currentTime, onlyFavourites, selectedVenues, selectedEventTypes, selectedAgeRanges });
    setSchedule(newSchedule);
  }, [currentTime, onlyFavourites, selectedVenues, selectedEventTypes, selectedAgeRanges, rawSchedule]);

  // Update time once a minute
  useEffect(() => {
    // In debug mode we want to be able to manually control time.
    if (!debug) {
      let timeout = setTimeout(() => {
        setCurrentTime(now());
      }, 60000);

      return () => clearTimeout(timeout);
    }
  });

  function toggleFavourite(event) {
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
        console.error("Error toggling favourite:", event, error);
      });
  }


  if (schedule === null) {
    return <p>Loading...</p>;
  }

  let filterProps = {
    schedule, onlyFavourites, setOnlyFavourites, selectedVenues, setSelectedVenues, selectedEventTypes, setSelectedEventTypes, selectedAgeRanges, setSelectedAgeRanges, debug, currentTime, setCurrentTime
  }

  return (
    <>
      <Messages />
      <Filters {...filterProps} />
      <Calendar schedule={ schedule } toggleFavourite={ toggleFavourite } authenticated={ apiToken !== null } />
    </>
  );
}

export default App;
