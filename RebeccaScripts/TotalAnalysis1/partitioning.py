import numpy as np
import sys
import time

class FeatureDataReader(object):
    """Reader for simulation data related to machine learning features
    
    Attributes:
        _dataDir: data directory
        _numParts: # of partitions in mesh
        _zoneOffsets: a map that takes zone id and returns partition and
                      offset within
        _indexCache: cache content of index file, which contains starting 
                     position (for seek) of each cycle
        _metaData: cache content of meta data file, which contains metrics 
                   names and zone ids
    """

    def __init__(self, dataDir, numParts):
        """Class constructor
        
        Args:
            dataDir: data directory
            numParts: # of partitions in mesh
        """
        self._dataDir = dataDir
        self._numParts = numParts
        
        self._zoneOffsets = {}
        self._indexCache = {}
        self._metaData = {}
        

    def readZone(self, run, cycle, zone):
        """Read data from a single mesh zone from a simulation cycle of a run
        
        Args:
            run: simulation run #
            cycle: simulation cycle # (time step)
            zone: mesh zone id
        
        Returns:
            1D numpy array of size (# of metrics)
        """
        zid = self._getZoneOffset(zone)
        index = self._readFileIndex(run, zid['part'])
        meta = self._readMetaData(zid['part'])
        
        fname = 'features_p%02d_r%03d.npy' % (zid['part'], run)
        nmetrics = len(meta['metrics'])
        offset = zid['offset'] * nmetrics * 4

        with open("%s/features/%s" % (self._dataDir,fname), 'rb') as fin:
            fin.seek(index[cycle] + offset)
            return np.fromfile(fin, dtype=np.float32, count=nmetrics)


    def readPartition(self, run, part, cycle):
        """Read data from entire mesh partition from a simulation cycle of a run
        
        Args:
            run: simulation run #
            part: mesh partition #
            cycle: simulation cycle # (time step)
            
        Returns:
            2D numpy array of shape (# of zones in partition X # of metrics)
        """
        index = self._readFileIndex(run, part)
        meta = self._readMetaData(part)

        fname = 'features_p%02d_r%03d.npy' % (part, run)
        nmetrics = len(meta['metrics'])
        nzones = len(meta['zones'])
        
        with open("%s/features/%s" % (self._dataDir,fname), 'rb') as fin:
            fin.seek(index[cycle])
            data = np.fromfile(fin, dtype=np.float32, count=nzones*nmetrics)
            return np.reshape(data, (nzones,nmetrics))


    def readAllCyclesForZone(self, run, zone):
        """Read data from all simulation cycles in a run of a single mesh zone
        
        Args:
            run: simulation run #
            zone: mesh zone id
            
        Returns:
            2D numpy array of shape (# of cycles X # of metrics)
        """
        zid = self._getZoneOffset(zone)
        index = self._readFileIndex(run, zid['part'])
        meta = self._readMetaData(zid['part'])
        
        fname = 'features_p%02d_r%03d.npy' % (zid['part'], run)
        nmetrics = len(meta['metrics'])
        offset = zid['offset'] * nmetrics * 4

        with open("%s/features/%s" % (self._dataDir,fname), 'rb') as fin:
            data = []
            for cycle in sorted(index.keys()):
                fin.seek(index[cycle] + offset)
                single = np.fromfile(fin, dtype=np.float32, count=nmetrics)
                data.append(np.reshape(single, (1,nmetrics)))
            return np.concatenate(data)


    def readAllZonesInCycle(self, run, cycle):
        """Read data from all mesh zones from a simulation cycle of a run
        
        Args:
            run: simulation run #
            cycle: simulation cycle # (time step)

        Returns:
            2D numpy array of shape (# of zones in mesh X # of metrics)
        """
        data = []
        for part in range(0, self._numParts):
            data.append(self.readPartition(run, part, cycle))
        return np.concatenate(data)


    def getPartitionZoneIds(self, part):
        """Get zone ids for a mesh partition
        
        Must ensure zone ids are in same order as read in from meta data file
        
        Args:
            part: mesh partition #
            
        Returns:
            1D numpy array of size (# of zones in partition)
        """
        zones = self._readMetaData(part)['zones']
        ids = [id for id in sorted(zones, key=zones.get)]
        return np.asarray(ids, dtype=np.int32)


    def getCycleZoneIds(self):
        """Get zone ids for entire mesh
        
        Returns:
            1D numpy array of size (# of zones in mesh)
        """
        data = []
        for part in range(0, self._numParts):
            data.append(self.getPartitionZoneIds(part))
        return np.concatenate(data)


    def getMetricNames(self):
        """Get names (or labels) of feature metrics
        
        Must ensure names are in same order as read in from meta data file
        All mesh partitions have the same set of metrics
        
        Returns:
            list of size (# of metrics)
        """
        metrics = self._readMetaData(0)['metrics']
        return [name for name in sorted(metrics, key=metrics.get)]


    def _readFileIndex(self, run, part):
        """Read file index and cache content into dictionary for mesh partition
        
        File index contains the seek position for the start of each cycle
        This speeds up the process for reading data from each cycle
        For each mesh partition, a separate dictionary is constructed that can 
        be indexed by the partition file name
        Essentially, this is a dictionary of dictionaries
        
        Args:
            run: simulation run #
            part: mesh partition #

        Returns:
            Dictionary with keys as cycle # and values as seek position
        """
        fname = 'indexes_p%02d_r%03d.txt' % (part, run)
        if fname not in self._indexCache:
            with open("%s/indexes/%s" % (self._dataDir,fname), 'r') as fin:
                index = {}
                for line in fin:
                    key,val = line.split(' -> ')
                    index[int(key)] = int(val)
                self._indexCache[fname] = index
        return self._indexCache[fname]


    def _readMetaData(self, part):
        """Read meta data and cache content into dictinary for mesh partition
        
        Meta data file contains feature metric names and mesh zone ids
        For each mesh partition, a separate dictionary is constructed that can 
        be indexed by the partition file name
        Each dictionary contains two elements: metric names and zone ids, both 
        of which are dictionaries themselves:
            Metrics is a dictionary with keys as names and values as offsets
            Zones is a dictionary with keys as ids and values as offsets
        The purpose of these two dictionaries is to enable users to find which 
        row or column within the 2D numpy array corresponds to which zone or 
        metric data value, respectively
        Essentially, this is a dictionary of dictionaries of dictionaries
        
        Args:
            part: mesh partition #
            
        Returns:
            Dictionary of two dictionaries: metric names and zone ids
        """
        fname = 'metadata_p%02d.txt' % part
        if fname not in self._metaData:
            with open("%s/features/%s" % (self._dataDir,fname), 'r') as fin:
                
                fin.readline()  # skip metrics header
                names = fin.readline().rstrip('\n').split(',')
                metrics = dict(zip(names, range(0, len(names))))

                fin.readline()  # skip zones header
                ids = fin.read().splitlines()
                zones = dict(zip(map(int, ids), range(0, len(ids))))

                self._metaData[fname] = {'metrics': metrics, 'zones': zones}
        return self._metaData[fname]


    def _getZoneOffset(self, zone):
        """Get mesh partition # and offset within partition for a single zone
        
        Construct a dictionary using zone ids as keys and partition plus offset 
        as values
        This requires first reading (and caching) the meta data files for all 
        mesh partitions
        
        Args:
            zone: mesh zone id
            
        Returns:
            Dictionary with keys as zone ids and values as partition and offset
        """
        if not self._zoneOffsets:
            for part in range(0, self._numParts):
                meta = self._readMetaData(part)
                for key in meta['zones'].keys():
                    self._zoneOffsets[key] = {'part': part, 
                                              'offset': meta['zones'][key]}
        return self._zoneOffsets[zone]


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print 'Usage: FeatureDataReader.py dataDir numParts'
        sys.exit(1)

    np.set_printoptions(suppress=True, precision=4)

    reader = FeatureDataReader(sys.argv[1], int(sys.argv[2]))
    (run, part, cycle, zone) = (25, 1, 6697, 944)

    print (reader.getMetricNames())

    running = 42
    while running < 50:
	    filename = "BYU_Alkemi_2017/RebeccaScripts/TotalAnalysis1/SSSSrun" + str(running) + ".csv"
	    Zone1 = open(filename, "w")
	    Zone1.write("Shape,ShapeCycle,ShSi,ShSiCy,Sr,SrCy,SrSi,SrSiCy\n")
	    Numbers = [1, 14]
	    x = 0
	    while x < 2:
		zoneIDs = reader.getPartitionZoneIds(Numbers[x])
		print str(zoneIDs[0]) + " " + str(zoneIDs[-1])
	    
		start = time.time()
		#for every zone do the analysis
		for z in zoneIDs:
			information = reader.readAllCyclesForZone(running, z)
			hOpoint = 0  #Oddy = 6
			hOcycle = 0
			hCN = 0  #ConditionNumber = 2
			hCNcycle = 0
			hAR = 0 #AspectRatio = 1
			hARcycle = 0
			hTpoint = 0 #Taper = 15
			hTcycle = 0
			hShpoint =100 #Shape = 8
			hShcycle = 0
			hShSi = 100 #ShapeAndSize = 9
			hShSicycle = 0
			hSr = 100 #Shear = 10
			hSrcycle = 0
			hSrSi = 100 #ShearAndSize = 11
			hSrSicycle = 0
			hLAng = 0 #LargestAngle = 5
			hLAngcycle = 0
	#go through all cycles of time in this zone and find relevant information	
			t = 0
			while t < len(information):
				if(information[t][6] > hOpoint):
					hOpoint = information[t][6]
					hOcycle = t
				if(information[t][2] > hCN):
					hCN = information[t][2]
					hCNcycle = t
				if(information[t][1] > hAR):
					hAR = information[t][1]
					hARcycle = t
				if(information[t][15] > hTpoint):
					hTpoint = information[t][1]
					hTcycle = t
				if(information[t][5] > hLAng):
					hLAng = information[t][5]
					hLAngcycle = t
				if(information[t][8] < hShpoint):
					hShpoint = information[t][8]
					hShpointcycle = t
				if(information[t][9] < hShSi):
					hShSi = information[t][9]
					hShSicycle = t
				if(information[t][10] < hSr):
					hSr = information[t][10]
					hSrcycle = t
				if(information[t][11] < hSrSi):
					hSrSi = information[t][11]
					hSrSicycle = t
				t += 1
			Zone1.write(str(z) + "," + str(hOpoint) + "," + str(hOcycle))
			Zone1.write("," + str(hCN) + "," + str(hCNcycle))
			Zone1.write("," + str(hAR) + "," + str(hARcycle))
			Zone1.write("," + str(hTpoint) + "," + str(hTcycle))
			Zone1.write("," + str(hLAng) + "," + str(hLAngcycle))
			Zone1.write("," + str(hShpoint) + "," + str(hShpointcycle))
			Zone1.write("," + str(hShSi) + "," + str(hShSicycle))
			Zone1.write("," + str(hSr) + "," + str(hSrcycle))
			Zone1.write("," + str(hSrSi) + "," + str(hSrSicycle) + "\n")
			#print str(z) + " "

		print str(running) + " " + str( time.time() - start)
		x +=1
	    Zone1.close()
	    running += 1
