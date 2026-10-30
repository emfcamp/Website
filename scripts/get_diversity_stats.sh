#!/bin/bash

categories=("age" "gender" "ethnicity" "sexuality")
# FIXME -- should probably figure out how to export disability information correctly

CONTAINER_NAME=emf-website-postgres-1
# CONTAINER_NAME=website-postgres-1 if on heaviside

CONTAINER_ID=$(docker ps -qf "NAME=${CONTAINER_NAME}")


# Get stats for all users
echo "++++++++++ All users ++++++++++"
for cat in "${categories[@]}";
do
  echo "===== ${cat} ====="
  docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT ${cat}, count(user_id) FROM diversity GROUP BY 1 ORDER BY 1;" 2> /dev/null
  echo
done

# Get stats for reviewers
echo "++++++++++ Reviewers ++++++++++"
for cat in "${categories[@]}";
do
  echo "===== ${cat} ====="
  docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT d.${cat}, count(d.user_id) FROM diversity d JOIN user_permission u ON d.user_id = u.user_id JOIN permission p ON u.permission_id = p.id WHERE p.name = 'cfp_reviewer' GROUP BY 1 ORDER BY 1;" 2> /dev/null
  echo
done

# Get stats for Speakers
echo "++++++++++ Speakers ++++++++++"
for cat in "${categories[@]}";
do
  echo "===== ${cat} ====="
  docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT d.${cat}, count(d.user_id) FROM diversity d JOIN schedule_item s ON d.user_id = s.user_id WHERE s.official_content GROUP BY 1 ORDER BY 1;" 2> /dev/null
  echo
done

# Get stats for  Invited Speakers
echo "++++++++++ Invited Speakers ++++++++++"
for cat in "${categories[@]}";
do
  echo "===== ${cat} ====="
  docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT d.${cat}, count(d.user_id) FROM diversity d JOIN \"user\" u on d.user_id = u.id where u.cfp_invite_reason != '' GROUP BY 1 ORDER BY 1;" 2> /dev/null
  echo
done

# Get Totals
echo "++++++++++ Totals with diversity ++++++++++"
echo "===== Attendees who filled in diversity ====="
docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT count(user_id) FROM diversity;" 2> /dev/null
echo "===== Reviewers ====="
docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT count(d.user_id) FROM diversity d JOIN user_permission u ON d.user_id = u.user_id JOIN permission p ON u.permission_id = p.id WHERE p.name = 'cfp_reviewer';" 2> /dev/null
echo "===== Speakers ====="
docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT count(d.user_id) FROM diversity d JOIN schedule_item s ON d.user_id = s.user_id WHERE s.official_content;" 2> /dev/null
echo "===== Invited Speakers ====="
docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT count(d.user_id) FROM diversity d JOIN \"user\" u on d.user_id = u.id where u.cfp_invite_reason != '';" 2> /dev/null

#
echo "++++++++++ Totals without diversity ++++++++++"
echo "===== Attendees ====="
docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT count(id) FROM \"user\";" 2> /dev/null
echo "===== Reviewers ====="
docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT DISTINCT count(u.user_id) FROM user_permission u JOIN permission p ON u.permission_id = p.id WHERE p.name = 'cfp_reviewer';" 2> /dev/null
echo "===== Speakers ====="
docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT DISTINCT count(user_id) FROM schedule_item WHERE official_content;" 2> /dev/null
echo "===== Invited Speakers ====="
docker exec -ti "${CONTAINER_ID}" psql -U postgres emf_site -c "SELECT DISTINCT count(id) FROM \"user\" WHERE cfp_invite_reason != '';" 2> /dev/null

