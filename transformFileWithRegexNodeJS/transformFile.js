// USAGE:  node ./transformFile.js sourceFile targetFile regexFile
// applies regex to sourceFile and writes to targetFile
// where regexFile is a text file with a regex on one line and the regex replacement on the next line
// if the next line is blank, the regex is replaced with the empty string
// use blank lines to separate each regex pair

// EXAMPLE:  node ./transformFile.js SourceFile.txt target.txt emailTemplateRegex.txt
// all regex substitutions in emailTemplateRegex.txt will be applied to SourceFile.txt and 
// the result written to target.txt

// skip first 2 elements:  node and path
const myArgs = process.argv.slice( 2 );
const sourceXMLName = myArgs[ 0 ];
const targetFileName = myArgs[ 1 ];
const regexFile = myArgs[ 2 ];

var fs = require('fs');

const regexData = fs.readFileSync( regexFile, 'utf8' );
const sourceData = fs.readFileSync( sourceXMLName, 'utf8' );

var fileContent = sourceData;

// apply to fileContent the regex found in regexData
var regexArray = regexData.split( '\n' );
for (var i = 0; i < regexArray.length; i++) {
    // skip blank separator lines
    if (regexArray[i].length <= 0) {
        continue;
    }

    let regexText = regexArray[i];
    let theRegex = new RegExp(regexText, 'gi');

    // identify if the regex is followed by a blank, replace with empty string
    // otherwise, replace with the regex replacement string
    let replaceWith = '';
    if ( i + 1 < regexArray.length && regexArray[i + 1].length > 0 ) {
        replaceWith = regexArray[i + 1];
        i++;
    }
    replaceWith = replaceWith.replace( /\\n/g, '\n' );
    fileContent = fileContent.replace(theRegex, replaceWith);
}

// write the modified contents to target file
if (targetFileName == 'STDOUT') {
    process.stdout.write( fileContent );
} else {
    fs.writeFileSync(targetFileName, fileContent, 'utf8');

    console.log( 'transformFileWithRegex:  DONE.' );
}
