#!/usr/bin/env python
from SPAdesPipeline.OLCspades.accessoryFunctions import *
import SPAdesPipeline.OLCspades.metadataprinter as metadataprinter
from threading import Thread
import subprocess
import time
__author__ = 'adamkoziol'


class CLARK(object):

    def objectprep(self):
        """Create objects to store data and metadata for each sample. Also, perform necessary file manipulations"""
        import createobject
        import fileprep
        # Move the files to subfolders and create objects
        self.runmetadata = createobject.ObjectCreation(self)
        if self.runmetadata.extension == '.fastq':
            # To streamline the CLARK process, decompress and combine .gz and paired end files as required
            printtime('Decompressing and combining .fastq files for CLARK analysis', self.start)
            fileprep.Fileprep(self)
        else:
            printtime('Using .fasta files for CLARK analysis', self.start)
            for sample in self.runmetadata.samples:
                sample.general.combined = sample.general.fastqfiles[0]
        # Set the targets
        self.settargets()

    def settargets(self):
        """Set the targets to be used in the analyses. Involves the path of the database files, the database files to
         use, and the level of classification for the analysis"""
        # Define the set targets call. Include the path to the script, the database path and files, as well
        # as the taxonomic rank to use
        printtime('Setting up database', self.start)
        self.targetcall = 'cd {} && ./set_targets.sh {} {} --{}'.format(self.clarkpath, self.databasepath,
                                                                        self.database, self.rank)
        subprocess.call(self.targetcall, shell=True, stdout=self.devnull, stderr=self.devnull)
        # Classify the metagenome(s)
        self.classifymetagenome()

    def classifymetagenome(self):
        """Run the classify metagenome of the CLARK package on the samples"""
        printtime('Classifying metagenomes', self.start)
        # Prepare the lists to be used to classify the metagenomes
        with open(self.filelist, 'wb') as filelist:
            with open(self.reportlist, 'wb') as reportlist:
                for sample in self.runmetadata.samples:
                    filelist.write(sample.general.combined + '\n')
                    reportlist.write(sample.general.combined.split('.')[0] + '\n')
        # Define the system call
        self.classifycall = 'cd {} && ./classify_metagenome.sh -O {} -R {} -n {}'.format(self.clarkpath,
                                                                                         self.filelist,
                                                                                         self.reportlist,
                                                                                         self.cpus)
        # Variable to store classification state
        classify = True
        for sample in self.runmetadata.samples:
            # Define the name of the .csv classification file
            sample.general.classification = sample.general.combined.split('.')[0] + '.csv'
            # If the file exists, then set classify to True
            if os.path.isfile(sample.general.classification):
                classify = False
        # Run the system call if the samples have not been classified
        if classify:
            # Run the call
            subprocess.call(self.classifycall, shell=True, stdout=self.devnull, stderr=self.devnull)
        # Estimate the abundance
        self.estimateabundance()

    def estimateabundance(self):
        """Estimate the abundance of taxonomic groups"""
        printtime('Estimating abundance of taxonomic groups', self.start)
        # Create and start threads
        for i in range(self.cpus):
            # Send the threads to the appropriate destination function
            threads = Thread(target=self.estimate, args=())
            # Set the daemon to true - something to do with thread management
            threads.setDaemon(True)
            # Start the threading
            threads.start()
        for sample in self.runmetadata.samples:
            self.abundancequeue.put(sample)
        self.abundancequeue.join()
        # Create reports
        self.reports()

    def estimate(self):
        while True:
            sample = self.abundancequeue.get()
            # Set the name of the abundance report
            sample.general.abundance = sample.general.combined.split('.')[0] + '_abundance.csv'
            # Define system calls
            sample.call = GenObject()
            sample.call.target = self.targetcall
            sample.call.classify = self.classifycall
            sample.call.abundance = \
                'cd {} && ./estimate_abundance.sh -D {} -F {} > {}'.format(self.clarkpath,
                                                                           self.databasepath,
                                                                           sample.general.classification,
                                                                           sample.general.abundance)
            # Run the system call (if necessary)
            if not os.path.isfile(sample.general.abundance):
                subprocess.call(sample.call.abundance, shell=True, stdout=self.devnull, stderr=self.devnull)
            self.abundancequeue.task_done()

    def reports(self):
        """Create reports from the abundance estimation"""
        import xlsxwriter
        printtime('Creating report', self.start)
        from csv import DictReader
        # Create a workbook to store the report. Using xlsxwriter rather than a simple csv format, as I want to be
        # able to have appropriately sized, multi-line cells
        workbook = xlsxwriter.Workbook('{}/abundance.xlsx'.format(self.reportpath))
        make_path(self.reportpath)
        # New worksheet to store the data
        worksheet = workbook.add_worksheet()
        # Add a bold format for header cells. Using a monotype font size 8
        bold = workbook.add_format({'bold': True, 'font_name': 'Courier New', 'font_size': 8})
        bold.set_align('center')
        # Format for data cells. Monotype, size 8, top vertically justified
        courier = workbook.add_format({'font_name': 'Courier New', 'font_size': 8})
        courier.set_align('top')
        # Set the custom width for 5 and 6 to be 15
        worksheet.set_column(5, 5, 15)
        worksheet.set_column(6, 6, 20)
        # Initialise the position within the worksheet to be (0,0)
        row = 0
        col = 0
        # List of the headers to use
        headers = ['Strain', 'Name', 'TaxID', 'Lineage', 'Count', 'Proportion_All(%)', 'Proportion_Classified(%)']
        # Add an additional header for .fasta analyses
        if self.runmetadata.extension == '.fasta':
            headers.insert(4, 'TotalBP')
        # Populate the headers
        for category in headers:
            # Write the data in the specified cell (row, col) using the bold format
            worksheet.write(row, col, category, bold)
            # Move to the next column to write the next category
            col += 1
        # Data starts in row 1
        row = 1
        # Initialise variables to hold the longest names; used in setting the column width
        longeststrain = 0
        longestname = 0
        longestlineage = 0
        # Extract all the taxonomic groups that pass the cutoff from the abundance file
        for sample in self.runmetadata.samples:
            # Every record starts at column 0
            col = 0
            # Write the strain name
            worksheet.write(row, col, sample.name, courier)
            col += 1
            # Initialise a dictionary to store the species above the cutoff in the sample
            sample.general.passfilter = list()
            # Abundance file as a dictionary
            abundancedict = DictReader(open(sample.general.abundance))
            # Filter abundance to taxIDs with at least self.cutoff% of the total proportion
            for result in abundancedict:
                # The UNKNOWN category doesn't contain a 'Lineage' column, and therefore, subsequent columns are
                # shifted out of proper alignment, and do not contain the appropriate data
                try:
                    if float(result['Proportion_All(%)']) > self.cutoff:
                        sample.general.passfilter.append(result)
                except ValueError:
                    pass
            # Determine the longest name of all the strains, and use it to set the width of column 0
            if len(sample.name) > longeststrain:
                longeststrain = len(sample.name)
                worksheet.set_column(0, 0, longeststrain)
            # Sort the abundance results based on the highest count
            sortedabundance = sorted(sample.general.passfilter, key=lambda x: int(x['Count']), reverse=True)
            # Set of contigs from the classification file. For some reason, certain contigs are represented multiple
            # times in the classification file. As far as I can tell, these multiple representations are always
            # classified the same, and, therefore, should be treated as duplicates, and ignored
            contigset = set()
            for result in sortedabundance:
                # Add the total number of base pairs classified for each TaxID. As only the total number of contigs
                # classified as a particular TaxID are presented in the report, it can be misleading if a large number
                # of small contigs are classified to a particular TaxID e.g. 56 contigs map to TaxID 28901, and 50
                # contigs map to TaxID 630, however, added together, those 56 contigs are 4705838 bp, while the 50
                # contigs added together are only 69602 bp. While this is unlikely a pure culture, only
                # 69602 / (4705838 + 69602) = 1.5% of the total bp map to TaxID 630 compared to 45% of the contigs
                if self.runmetadata.extension == '.fasta':
                    # Initialise a variable to store the total bp mapped to the TaxID
                    result['TotalBP'] = int()
                    # Read the classification file into a dictionary
                    classificationdict = DictReader(open(sample.general.classification))
                    # Read through each contig classification in the dictionary
                    for contig in classificationdict:
                        # Pull out each contig with a TaxID that matches the TaxID of the result of interest, and
                        # is not present in a set of contigs that have already been added to the dictionary
                        if result['TaxID'] == contig[' Assignment'] and contig['Object_ID'] not in contigset:
                            # Increment the total bp mapping to the TaxID by the integer of each contig
                            result['TotalBP'] += int(contig[' Length'])
                            # Avoid duplicates by adding the contig name to the set of contigs
                            contigset.add(contig['Object_ID'])
                # Print the results to file
                # Ignore the first header, as it is the strain name, which has already been added to the report
                dictionaryheaders = headers[1:]
                for header in dictionaryheaders:
                    data = result[header]
                    worksheet.write(row, col, data, courier)
                    col += 1
                    # Determine the longest name of all the matches, and use it to set the width of column 0
                    if len(result['Name']) > longestname:
                        longestname = len(result['Name'])
                        worksheet.set_column(1, 1, longestname)
                    # Do the same for the lineages
                    if len(result['Lineage']) > longestlineage:
                        longestlineage = len(result['Lineage'])
                        worksheet.set_column(3, 3, longestlineage)
                # Increase the row
                row += 1
                # Set the column to 1
                col = 1
        # Close the workbook
        workbook.close()

    def __init__(self, args, pipelinecommit, startingtime, scriptpath):
        import multiprocessing
        from Queue import Queue
        # Initialise variables
        self.commit = str(pipelinecommit)
        self.start = startingtime
        self.homepath = scriptpath
        # Define variables based on supplied arguments
        self.args = args
        self.path = os.path.join(args.path, '')
        assert os.path.isdir(self.path), u'Supplied path is not a valid directory {0!r:s}'.format(self.path)
        self.sequencepath = os.path.join(args.sequencepath, '')
        assert os.path.isdir(self.sequencepath), u'Supplied sequence path is not a valid directory {0!r:s}' \
            .format(self.sequencepath)
        self.databasepath = os.path.join(args.databasepath, '')
        assert os.path.isdir(self.databasepath), u'Supplied sequence path is not a valid directory {0!r:s}' \
            .format(self.databasepath)
        self.reportpath = os.path.join(self.path, 'reports')
        # Use the argument for the number of threads to use, or default to the number of cpus in the system
        self.cpus = int(args.threads if args.threads else multiprocessing.cpu_count())
        self.runmetadata = MetadataObject()
        # Set variables from the arguments
        self.database = args.database
        self.rank = args.rank
        self.clarkpath = args.clarkpath
        self.cutoff = float(args.cutoff) * 100
        # Initialise variables for the analysis
        self.targetcall = ''
        self.classifycall = ''
        self.devnull = open(os.devnull, 'wb')
        self.filelist = '{}sampleList.txt'.format(self.path)
        self.reportlist = '{}reportList.txt'.format(self.path)
        self.abundancequeue = Queue()
        self.datapath = ''
        # Create the objects
        self.objectprep()
        # Optionally filter the .fastq reads based on taxonomic assignment
        if args.filter:
            import filtermetagenome
            filtermetagenome.PipelineInit(self)
        # Print the metadata to file
        metadataprinter.MetadataPrinter(self)


if __name__ == '__main__':
    # Argument parser for user-inputted values, and a nifty help menu
    from argparse import ArgumentParser
    # Get the current commit of the pipeline from git
    # Extract the path of the current script from the full path + file name
    homepath = os.path.split(os.path.abspath(__file__))[0]
    # Find the commit of the script by running a command to change to the directory containing the script and run
    # a git command to return the short version of the commit hash
    commit = subprocess.Popen('cd {} && git rev-parse --short HEAD'.format(homepath),
                              shell=True, stdout=subprocess.PIPE).communicate()[0].rstrip()
    # Parser for arguments
    parser = ArgumentParser(description='Automates CLARK metagenome software')
    parser.add_argument('path',
                        help='Specify input directory')
    parser.add_argument('-s', '--sequencepath',
                        required=True,
                        help='Path of .fastq(.gz) files to process.')
    parser.add_argument('-d', '--databasepath',
                        required=True,
                        help='Path of CLARK database files to use.')
    parser.add_argument('-C', '--clarkpath',
                        required=True,
                        help='Path to the CLARK scripts')
    parser.add_argument('-r', '--rank',
                        default='species',
                        help='Choose the taxonomic rank to use in the analysis: species (the default value), genus, '
                             'family, order, class or phylum')
    parser.add_argument('-D', '--database',
                        default='bacteria',
                        help='Choose the database to use in the analysis (one or more from: bacteria, viruses, human,'
                             'and custom. To select more than one, use commas to separate your selection. Custom'
                             'databases need to be set up before they will work')
    parser.add_argument('-t', '--threads',
                        help='Number of threads. Default is the number of cores in the system')
    parser.add_argument('-f', '--filter',
                        action='store_true',
                        help='Optionally split the samples based on taxonomic assignment')
    parser.add_argument('-c', '--cutoff',
                        default=0.01,
                        help='Cutoff value for setting taxIDs to use when filtering fastq files. Defaults to 1 percent.'
                             ' Please note that you must use a decimal format: enter 0.05 to get a 5 percent cutoff.')
    # Get the arguments into an object
    arguments = parser.parse_args()

    # TODO Implement --rank and --database, and provide a way to easily create a custom database

    # Define the start time
    start = time.time()

    # Run the script
    CLARK(arguments, commit, start, homepath)

    # Print a bold, green exit statement
    print '\033[92m' + '\033[1m' + "\nElapsed Time: %0.2f seconds" % (time.time() - start) + '\033[0m'
