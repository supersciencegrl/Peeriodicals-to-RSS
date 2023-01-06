# Peeriodicals to RSS

This repository is made to interact with the [High-Throughput Automation in R and D](https://peeriodicals.com/peeriodicals/high-throughput-automation-in-rampd) Peeriodicals site. It can readily be edited to work with other Peeriodicals too! 

The High-Throughput Automation in R&D Peeriodicals overlay journal aims to be a repository of peer-reviewed articles on the use of HTE for small molecules and related topics in R&D laboratories. It is currently curated by Nessa Carson and Luigi da Vi&agrave;. 

## Usage
The file:
```
https://raw.githubusercontent.com/supersciencegrl/Peeriodicals-to-RSS/main/rss.xml
```
may be added directly to an RSS reader, and will then update automatically like any other RSS feed. 

## Function
This script is made to run automatically once per day _via_ GitHub actions. It will add any new publications in the Peeriodicals to the rss feed. 

The automation script _execute.py_ works as such:
- Reads in the html from the HTE [Peeriodicals](https://peeriodicals.com/peeriodicals/high-throughput-automation-in-rampd) site
- Converts each publication from the Peeriodicals into a dictionary, using both the Peeriodicals information and records from CrossRef
- Assembles the list of publications into an RSS feed. 
