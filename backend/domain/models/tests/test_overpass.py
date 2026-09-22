import unittest
import xml.etree.ElementTree as ET

from domain.models.overpass import filter_osm_xml_to_polygon


class OfficialOsmPolygonFilterTests(unittest.TestCase):
    def test_keeps_relevant_crossing_and_enclosing_ways(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <bounds minlat="0" minlon="0" maxlat="10" maxlon="10"/>
  <node id="1" lat="5" lon="-1"/>
  <node id="2" lat="5" lon="11"/>
  <node id="3" lat="-1" lon="-1"/>
  <node id="4" lat="-1" lon="11"/>
  <node id="5" lat="11" lon="11"/>
  <node id="6" lat="11" lon="-1"/>
  <node id="7" lat="20" lon="20"/>
  <node id="8" lat="20" lon="21"/>
  <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="footway"/></way>
  <way id="11"><nd ref="3"/><nd ref="4"/><nd ref="5"/><nd ref="6"/><nd ref="3"/><tag k="building" v="yes"/></way>
  <way id="12"><nd ref="7"/><nd ref="8"/><tag k="highway" v="service"/></way>
</osm>"""
        result = ET.fromstring(
            filter_osm_xml_to_polygon(
                xml,
                [(0, 0), (10, 0), (10, 10), (0, 10)],
            )
        )

        self.assertEqual(
            {element.get("id") for element in result.findall("way")},
            {"10", "11"},
        )
        self.assertEqual(
            {element.get("id") for element in result.findall("node")},
            {"1", "2", "3", "4", "5", "6"},
        )

    def test_keeps_complete_untagged_members_of_building_relation(self):
        xml = """<osm version="0.6">
  <node id="1" lat="1" lon="1"/>
  <node id="2" lat="1" lon="2"/>
  <node id="3" lat="2" lon="2"/>
  <node id="4" lat="2" lon="1"/>
  <way id="20"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="4"/><nd ref="1"/></way>
  <relation id="30">
    <member type="way" ref="20" role="outer"/>
    <tag k="type" v="multipolygon"/>
    <tag k="building" v="yes"/>
  </relation>
</osm>"""
        result = ET.fromstring(
            filter_osm_xml_to_polygon(
                xml,
                [(0, 0), (10, 0), (10, 10), (0, 10)],
            )
        )

        self.assertEqual([element.get("id") for element in result.findall("relation")], ["30"])
        self.assertEqual([element.get("id") for element in result.findall("way")], ["20"])
        self.assertEqual(
            {element.get("id") for element in result.findall("node")},
            {"1", "2", "3", "4"},
        )

    def test_excludes_irrelevant_elements_inside_polygon(self):
        xml = """<osm version="0.6">
  <node id="1" lat="1" lon="1"/>
  <node id="2" lat="2" lon="2"/>
  <way id="40"><nd ref="1"/><nd ref="2"/><tag k="landuse" v="grass"/></way>
  <relation id="50"><member type="way" ref="40" role=""/><tag k="type" v="route"/></relation>
</osm>"""
        result = ET.fromstring(
            filter_osm_xml_to_polygon(
                xml,
                [(0, 0), (10, 0), (10, 10), (0, 10)],
            )
        )

        self.assertEqual(result.findall("node"), [])
        self.assertEqual(result.findall("way"), [])
        self.assertEqual(result.findall("relation"), [])


if __name__ == "__main__":
    unittest.main()
